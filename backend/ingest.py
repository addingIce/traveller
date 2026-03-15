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

    async def add_messages_task(m: Message):
        from graphiti_core.nodes import EpisodicNode
        from graphiti_core.errors import NodeNotFoundError
        from graphiti_core.utils.datetime_utils import utc_now
        import time

        print(f"Task started for message: {m.uuid}")
        # 增加延时以缓解 Rate Limit（可配置）
        delay_s = float(os.getenv("GRAPHITI_MESSAGE_DELAY_SECONDS", "0"))
        if delay_s > 0:
            print(f"Waiting {delay_s}s to avoid rate limit...")
            await asyncio.sleep(delay_s)
        
        settings = get_settings()
        try:
            async for graphiti in get_graphiti_it(settings):
                # 检查节点是否存在，不存在则创建
                try:
                    await EpisodicNode.get_by_uuid(graphiti.driver, m.uuid)
                    print(f"Node {m.uuid} already exists.")
                except NodeNotFoundError:
                    print(f"Node {m.uuid} not found, creating it first...")
                    new_ep = EpisodicNode(
                        uuid=m.uuid,
                        name=m.name or f"Message {m.uuid[:8]}",
                        group_id=request.group_id,
                        content=f'{m.role or ""}({m.role_type}): {m.content}',
                        created_at=utc_now(),
                        valid_at=m.timestamp or utc_now(),
                        source=EpisodeType.message,
                        source_description=m.source_description or "Zep Ingest",
                    )
                    await new_ep.save(graphiti.driver)
                    print(f"Node {m.uuid} created and saved.")

                print(f"Adding episode to graphiti: {m.uuid}")
                await graphiti.add_episode(
                    uuid=m.uuid,
                    group_id=request.group_id,
                    name=m.name or f"Message {m.uuid[:8]}",
                    episode_body=f'{m.role or ""}({m.role_type}): {m.content}',
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
        await async_worker.queue.put(partial(add_messages_task, m))

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
