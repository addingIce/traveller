import asyncio
import os
from contextlib import asynccontextmanager
from functools import partial

from fastapi import APIRouter, FastAPI, status
from graphiti_core.nodes import EpisodeType  # type: ignore
from graphiti_core.utils.maintenance.graph_data_operations import clear_data  # type: ignore

from graph_service.dto import AddEntityNodeRequest, AddMessagesRequest, Message, Result
from pydantic import BaseModel
from graph_service.zep_graphiti import ZepGraphitiDep


# 存储已取消的 group_id（小说集合）
cancelled_groups: set[str] = set()


class AsyncWorker:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.task = None

    async def worker(self):
        while True:
            try:
                print(f'Got a job: (size of remaining queue: {self.queue.qsize()})')
                job = await self.queue.get()
                await job()
            except asyncio.CancelledError:
                break

    async def start(self):
        self.task = asyncio.create_task(self.worker())

    async def stop(self):
        if self.task:
            self.task.cancel()
            await self.task
        while not self.queue.empty():
            self.queue.get_nowait()


async_worker = AsyncWorker()


class _Person(BaseModel):
    """人物"""


class _Place(BaseModel):
    """地点"""


class _Organization(BaseModel):
    """组织"""


class _Item(BaseModel):
    """物品"""


class _Concept(BaseModel):
    """概念"""


ENTITY_TYPES = {
    "人物": _Person,
    "地点": _Place,
    "组织": _Organization,
    "物品": _Item,
    "概念": _Concept,
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    await async_worker.start()
    yield
    await async_worker.stop()


router = APIRouter(lifespan=lifespan)


@router.post('/messages', status_code=status.HTTP_202_ACCEPTED)
async def add_messages(
    request: AddMessagesRequest,
):
    from graph_service.config import get_settings
    from graph_service.zep_graphiti import get_graphiti as get_graphiti_it

    async def add_messages_task(m: Message, group_id: str):
        from graphiti_core.nodes import EpisodicNode
        from graphiti_core.errors import NodeNotFoundError
        from graphiti_core.utils.datetime_utils import utc_now
        import time

        # 检查是否已被取消
        if group_id in cancelled_groups:
            print(f"[SKIP] Group {group_id} has been cancelled, skipping message {m.uuid}")
            return

        print(f"Task started for message: {m.uuid}")
        # 增加延时以缓解 Rate Limit（可配置）
        delay_s = float(os.getenv("GRAPHITI_MESSAGE_DELAY_SECONDS", "0"))
        if delay_s > 0:
            print(f"Waiting {delay_s}s to avoid rate limit...")
            await asyncio.sleep(delay_s)
        
        settings = get_settings()
        try:
            async for graphiti in get_graphiti_it(settings):
                # 再次检查是否已被取消（可能在等待期间被取消）
                if group_id in cancelled_groups:
                    print(f"[SKIP] Group {group_id} was cancelled during processing, aborting message {m.uuid}")
                    return

                # 检查节点是否存在，不存在则创建
                try:
                    await EpisodicNode.get_by_uuid(graphiti.driver, m.uuid)
                    print(f"Node {m.uuid} already exists.")
                except NodeNotFoundError:
                    print(f"Node {m.uuid} not found, creating it first...")
                    new_ep = EpisodicNode(
                        uuid=m.uuid,
                        name=m.name or f"Message {m.uuid[:8]}",
                        group_id=group_id,
                        content=f'{m.role or ""}({m.role_type}): {m.content}',
                        created_at=utc_now(),
                        valid_at=m.timestamp or utc_now(),
                        source=EpisodeType.message,
                        source_description=m.source_description or "Zep Ingest",
                    )
                    await new_ep.save(graphiti.driver)
                    print(f"Node {m.uuid} created and saved.")

                # 最终检查是否已被取消
                if group_id in cancelled_groups:
                    print(f"[SKIP] Group {group_id} was cancelled, skipping episode {m.uuid}")
                    return

                print(f"Adding episode to graphiti: {m.uuid}")
                # 格式化 episode_body：role 为空时只显示 role_type，避免空括号
                episode_body = f'{m.role}({m.role_type}): {m.content}' if m.role else f'({m.role_type}): {m.content}'
                await graphiti.add_episode(
                    uuid=m.uuid,
                    group_id=group_id,
                    name=m.name or f"Message {m.uuid[:8]}",
                    episode_body=episode_body,
                    reference_time=m.timestamp or utc_now(),
                    source=EpisodeType.message,
                    source_description=m.source_description or "Zep Ingest",
                    entity_types=ENTITY_TYPES,
                )
                print(f"Episode processed successfully: {m.uuid}")
        except Exception as e:
            import traceback
            print(f"ERROR in add_messages_task: {e}")
            traceback.print_exc()

    for m in request.messages:
        await async_worker.queue.put(partial(add_messages_task, m, request.group_id))

    return Result(message='Messages added to processing queue', success=True)


@router.post('/entity-node', status_code=status.HTTP_201_CREATED)
async def add_entity_node(
    request: AddEntityNodeRequest,
    graphiti: ZepGraphitiDep,
):
    node = await graphiti.save_entity_node(
        uuid=request.uuid,
        group_id=request.group_id,
        name=request.name,
        summary=request.summary,
    )
    return node


@router.delete('/entity-edge/{uuid}', status_code=status.HTTP_200_OK)
async def delete_entity_edge(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_entity_edge(uuid)
    return Result(message='Entity Edge deleted', success=True)


@router.delete('/group/{group_id}', status_code=status.HTTP_200_OK)
async def delete_group(group_id: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_group(group_id)
    return Result(message='Group deleted', success=True)


@router.delete('/episode/{uuid}', status_code=status.HTTP_200_OK)
async def delete_episode(uuid: str, graphiti: ZepGraphitiDep):
    await graphiti.delete_episodic_node(uuid)
    return Result(message='Episode deleted', success=True)


@router.post('/clear', status_code=status.HTTP_200_OK)
async def clear(
    graphiti: ZepGraphitiDep,
):
    await clear_data(graphiti.driver)
    await graphiti.build_indices_and_constraints()
    return Result(message='Graph cleared', success=True)


@router.post('/cancel/{group_id}', status_code=status.HTTP_200_OK)
async def cancel_group(group_id: str):
    """取消指定小说集合的所有待处理消息"""
    cancelled_groups.add(group_id)
    print(f"[CANCEL] Group {group_id} has been marked as cancelled")
    return Result(message=f'Group {group_id} cancelled', success=True)


@router.delete('/cancel/{group_id}', status_code=status.HTTP_200_OK)
async def remove_cancel(group_id: str):
    """移除取消标记（用于重新处理）"""
    cancelled_groups.discard(group_id)
    print(f"[UNCANCEL] Group {group_id} has been removed from cancelled list")
    return Result(message=f'Group {group_id} uncancelled', success=True)
