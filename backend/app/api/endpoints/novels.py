"""
小说上传和管理 API 端点
"""
import os
import re
import time
import asyncio
import httpx
from typing import List, Optional
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Request, status
from pydantic import BaseModel

from zep_python.client import AsyncZep
from zep_python import Message

router = APIRouter()

# Graphiti API 配置
GRAPHITI_API_URL = "http://localhost:8003"

# ========== 数据模型 ==========

class NovelInfo(BaseModel):
    """小说信息"""
    collection_name: str
    title: str
    status: str  # processing/completed/failed
    created_at: str
    chunks_count: int = 0
    progress: float = 0.0
    stage: Optional[str] = None  # chunking/writing/extracting/dedup/completed
    eta_seconds: Optional[int] = None


class UploadResponse(BaseModel):
    """上传响应"""
    collection_name: str
    title: str
    status: str
    message: str
    estimated_time: Optional[int] = None


class ProcessStatusResponse(BaseModel):
    """处理状态响应"""
    collection_name: str
    status: str  # processing/completed/failed
    progress: float  # 0-100
    chunks_processed: int
    total_chunks: int
    stage: Optional[str] = None  # chunking/writing/extracting/dedup/completed
    eta_seconds: Optional[int] = None  # 预计剩余时间
    error_message: Optional[str] = None


class DeleteResponse(BaseModel):
    """删除响应"""
    collection_name: str
    success: bool
    message: str


class NovelsListResponse(BaseModel):
    """小说列表响应"""
    novels: List[NovelInfo]

from app.services.novel_service import (
    generate_collection_name, 
    smart_chunk_content, 
    monitor_entity_extraction, 
    process_novel_task, 
    deduplicate_entities_in_collection,
    get_entity_count, 
    check_zep_messages, 
    observe_entity_growth
)

async def validate_upload_file(file: UploadFile) -> None:
    """验证上传的文件"""
    # 检查文件类型
    if not file.filename or not file.filename.endswith('.txt'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅支持 .txt 文本文件"
        )
    
    # 检查文件大小（10MB 限制）
    max_size = 10 * 1024 * 1024  # 10MB
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件大小不能超过 10MB"
        )
    
    # 检查编码（尝试 UTF-8 解码）
    try:
        content.decode('utf-8')
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="文件编码必须是 UTF-8"
        )
    
    # 重置文件指针
    await file.seek(0)

# ========== API 端点 ==========

@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
async def upload_novel(
    file: UploadFile = File(...),
    title: Optional[str] = Form(None),
    request: Request = None
):
    """
    上传小说文件并启动处理
    
    - file: 小说文本文件（.txt，UTF-8，最大 10MB）
    - title: 小说标题（可选，默认使用文件名）
    """
    # 获取 Zep 客户端
    client = getattr(request.app.state, "zep", None)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Zep 服务未就绪"
        )
    
    # 获取状态存储
    status_store = getattr(request.app.state, "processing_tasks", {})
    graph_cache = getattr(request.app.state, "graph_cache", {})
    
    # 获取 Neo4j 驱动
    neo4j_driver = getattr(request.app.state, "neo4j_driver", None)
    
    # 验证文件
    await validate_upload_file(file)
    
    # 读取文件内容
    content = await file.read()
    text_content = content.decode('utf-8')
    
    # 确定标题
    novel_title = title if title else (file.filename or "未命名").replace('.txt', '')
    
    # 生成集合名称
    collection_name = generate_collection_name(novel_title)
    
    # 初始化状态
    status_store[collection_name] = {
        "status": "queued",
        "progress": 0.0,
        "chunks_processed": 0,
        "total_chunks": 0,
        "error_message": None,
        "created_at": datetime.utcnow().isoformat(),
        "title": novel_title,
        "stage": "queued",  # 当前阶段：queued/chunking/writing/extracting/dedup/completed
        "failed_batches": [],  # 失败的批次号
        "eta_seconds": 0,  # 预估剩余时间
        "start_time": None,  # 开始处理时间
    }
    
    # 启动异步处理任务
    asyncio.create_task(process_novel_task(collection_name, text_content, novel_title, client, status_store, neo4j_driver))
    
    # 预估处理时间（基于文件大小）
    chunks_count = len([c for c in text_content.split("\n\n") if len(c.strip()) > 20])
    estimated_time = max(10, chunks_count * 2)  # 每个片段约 2 秒
    
    return UploadResponse(
        collection_name=collection_name,
        title=novel_title,
        status="queued",
        message="小说已加入处理队列",
        estimated_time=estimated_time
    )


@router.get("", response_model=NovelsListResponse)
async def get_novels_list(request: Request):
    """
    获取所有已上传的小说列表
    从 Neo4j 中获取所有有数据的小说，并补充内存中的处理状态
    """
    driver = getattr(request.app.state, "neo4j_driver", None)
    status_store = getattr(request.app.state, "processing_tasks", {})
    
    novels = []
    chunk_progress_statuses = {"processing"}

    def resolve_chunks_count(status_value: str, task_info: dict, entity_count: int) -> int:
        # 统一口径：处理中用 chunks_processed，其余回退 entity_count
        if status_value in chunk_progress_statuses:
            return int(task_info.get("chunks_processed", 0) or 0)
        return int(entity_count or 0)

    def merge_duplicate(existing: NovelInfo, incoming: NovelInfo) -> NovelInfo:
        # 优先保留信息更完整的记录，避免显示 collection_name 作为标题
        title = existing.title
        if (not title or title.startswith("novel_")) and incoming.title and not incoming.title.startswith("novel_"):
            title = incoming.title
        created_at = existing.created_at or incoming.created_at
        status = existing.status if existing.status != "unknown" else incoming.status
        chunks_count = existing.chunks_count if existing.chunks_count > 0 else incoming.chunks_count
        # 优先使用有值的 progress、stage、eta_seconds
        progress = existing.progress if existing.progress > 0 else incoming.progress
        stage = existing.stage or incoming.stage
        eta_seconds = existing.eta_seconds if existing.eta_seconds is not None else incoming.eta_seconds
        return NovelInfo(
            collection_name=existing.collection_name,
            title=title,
            status=status,
            created_at=created_at,
            chunks_count=chunks_count,
            progress=progress,
            stage=stage,
            eta_seconds=eta_seconds,
        )
    
    # 优先从 Neo4j 获取所有有数据的小说
    if driver:
        try:
            async with driver.session() as session:
                # 获取所有 Novel 节点，以及每个小说的实体数量（按名称去重，与图谱一致）
                novel_query = """
                MATCH (novel:Novel)
                OPTIONAL MATCH (entity:Entity {group_id: novel.collection_name})
                WITH novel, COUNT(DISTINCT entity.name) as entity_count
                ORDER BY novel.created_at DESC
                RETURN novel.collection_name as collection_name,
                       novel.title as title,
                       novel.created_at as created_at,
                       novel.status as novel_status,
                       entity_count
                """
                result = await session.run(novel_query)
                novel_collections = set()
                async for record in result:
                    collection_name = record["collection_name"]
                    novel_title = record["title"] or collection_name
                    created_at = record["created_at"] or ""
                    novel_status = record["novel_status"] or "completed"
                    entity_count = record["entity_count"]
                    novel_collections.add(collection_name)
                    
                    # 从 status_store 获取实时状态（如果在处理中）
                    task_info = status_store.get(collection_name, {})
                    status = task_info.get("status", novel_status)
                    chunks_count = resolve_chunks_count(status, task_info, entity_count)
                    progress = task_info.get("progress", 100.0 if status in ["completed", "extracting", "ready"] else 0.0)
                    
                    novels.append(NovelInfo(
                        collection_name=collection_name,
                        title=novel_title,
                        status=status,
                        created_at=created_at,
                        chunks_count=chunks_count,
                        progress=progress,
                        stage=task_info.get("stage"),
                        eta_seconds=task_info.get("eta_seconds")
                    ))
                
                # 获取没有 Novel 节点的旧小说（只有 Entity 节点）
                old_novels_query = """
                MATCH (e:Entity)
                WHERE e.group_id STARTS WITH 'novel_'
                WITH e.group_id as group_id, COUNT(DISTINCT e.name) as entity_count
                OPTIONAL MATCH (n:Novel {collection_name: group_id})
                WITH group_id, entity_count, n
                WHERE n IS NULL
                RETURN group_id, entity_count
                ORDER BY group_id
                """
                result = await session.run(old_novels_query)
                async for record in result:
                    collection_name = record["group_id"]
                    entity_count = record["entity_count"]
                    
                    # 从 status_store 获取额外的元数据（如果有）
                    task_info = status_store.get(collection_name, {})
                    old_status = task_info.get("status", "completed")
                    progress = task_info.get("progress", 100.0 if old_status in ["completed", "extracting", "ready"] else 0.0)
                    
                    novels.append(NovelInfo(
                        collection_name=collection_name,
                        title=task_info.get("title", collection_name),  # 使用 collection_name 作为标题
                        status=old_status,
                        created_at=task_info.get("created_at", ""),
                        chunks_count=resolve_chunks_count(old_status, task_info, entity_count),
                        progress=progress,
                        stage=task_info.get("stage"),
                        eta_seconds=task_info.get("eta_seconds")
                    ))

                # 获取仅有 Episodic 数据的孤儿小说（没有 Novel 和 Entity 时也要可见，便于用户停止任务）
                episodic_only_query = """
                MATCH (ep:Episodic)
                WHERE ep.group_id STARTS WITH 'novel_'
                WITH ep.group_id as group_id, COUNT(ep) as episodic_count
                OPTIONAL MATCH (n:Novel {collection_name: group_id})
                OPTIONAL MATCH (e:Entity {group_id: group_id})
                WITH group_id, episodic_count, n, COUNT(DISTINCT e) as entity_count
                WHERE n IS NULL AND entity_count = 0
                RETURN group_id, episodic_count
                ORDER BY group_id
                """
                result = await session.run(episodic_only_query)
                async for record in result:
                    collection_name = record["group_id"]
                    episodic_count = int(record["episodic_count"] or 0)

                    task_info = status_store.get(collection_name, {})
                    inferred_status = task_info.get("status", "extracting")
                    progress = task_info.get("progress", 0.0)
                    if progress <= 0 and episodic_count > 0:
                        # 无 total_chunks 时，至少体现“已写入并在提取中”
                        progress = 33.3

                    novels.append(NovelInfo(
                        collection_name=collection_name,
                        title=task_info.get("title", collection_name),
                        status=inferred_status,
                        created_at=task_info.get("created_at", ""),
                        chunks_count=episodic_count,
                        progress=progress,
                        stage=task_info.get("stage", "extracting"),
                        eta_seconds=task_info.get("eta_seconds")
                    ))
        except Exception as e:
            print(f"[ERROR] Failed to get novels from Neo4j: {e}")
    
    # 无论 Neo4j 查询结果如何，都补齐仅存在于内存任务中的新上传小说
    # 这样前端上传后无需刷新即可看到新小说
    existing_collections = {n.collection_name for n in novels}
    for collection_name, task_info in status_store.items():
        if collection_name in existing_collections:
            continue
        status_value = task_info.get("status", "unknown")
        chunks_count = resolve_chunks_count(status_value, task_info, 0)
        progress = task_info.get("progress", 0.0)

        novels.append(NovelInfo(
            collection_name=collection_name,
            title=task_info.get("title", collection_name),
            status=status_value,
            created_at=task_info.get("created_at", ""),
            chunks_count=chunks_count,
            progress=progress,
            stage=task_info.get("stage"),
            eta_seconds=task_info.get("eta_seconds")
        ))

    # 兜底去重：即使查询层出现重复，也保证返回列表按 collection_name 唯一
    deduped_novels = {}
    for novel in novels:
        if novel.collection_name in deduped_novels:
            print(f"[WARNING] Duplicate novel record detected for collection={novel.collection_name}, merging records")
            deduped_novels[novel.collection_name] = merge_duplicate(deduped_novels[novel.collection_name], novel)
        else:
            deduped_novels[novel.collection_name] = novel
    novels = list(deduped_novels.values())
    
    # 按创建时间倒序排列
    novels.sort(key=lambda x: x.created_at, reverse=True)
    
    return NovelsListResponse(novels=novels)


@router.get("/{collection_name}/status", response_model=ProcessStatusResponse)
async def get_novel_status(collection_name: str, request: Request):
    """
    获取指定小说的处理状态
    """
    status_store = getattr(request.app.state, "processing_tasks", {})
    driver = getattr(request.app.state, "neo4j_driver", None)

    # 1) 优先返回内存中的实时状态
    if collection_name in status_store:
        task_info = status_store[collection_name]
        return ProcessStatusResponse(
            collection_name=collection_name,
            status=task_info.get("status", "unknown"),
            progress=task_info.get("progress", 0.0),
            chunks_processed=task_info.get("chunks_processed", 0),
            total_chunks=task_info.get("total_chunks", 0),
            stage=task_info.get("stage"),
            eta_seconds=task_info.get("eta_seconds"),
            error_message=task_info.get("error_message")
        )

    # 2) 内存没有时回退到 Neo4j 的 Novel 状态
    if driver:
        try:
            async with driver.session() as session:
                query = """
                MATCH (n:Novel {collection_name: $collection_name})
                RETURN n.status as status
                LIMIT 1
                """
                result = await session.run(query, collection_name=collection_name)
                record = await result.single()

                if record:
                    db_status = record["status"] or "unknown"
                    if db_status in {"ready", "completed", "failed"}:
                        progress = 100.0
                    elif db_status in {"processing", "extracting", "queued"}:
                        progress = 0.0
                    else:
                        progress = 0.0

                    return ProcessStatusResponse(
                        collection_name=collection_name,
                        status=db_status,
                        progress=progress,
                        chunks_processed=0,
                        total_chunks=0,
                        stage="completed" if db_status in {"ready", "completed"} else None,
                        eta_seconds=None,
                        error_message=None
                    )
        except Exception as e:
            print(f"[ERROR] Failed to get status from Neo4j: {e}")

    # 3) 内存和数据库都没有，返回不存在
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="小说不存在"
    )


@router.delete("/{collection_name}", response_model=DeleteResponse)
async def delete_novel(collection_name: str, request: Request):
    """
    删除小说及其相关数据
    """
    status_store = getattr(request.app.state, "processing_tasks", {})
    client = getattr(request.app.state, "zep", None)
    driver = getattr(request.app.state, "neo4j_driver", None)
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Zep 服务未就绪"
        )
    
    deleted_entities = 0
    deleted_relationships = 0
    deleted_sessions = 0
    errors = []
    
    try:
        # 1. 先获取所有关联的 Session ID（用于删除 Zep 数据）
        session_ids = []
        if driver:
            try:
                async with driver.session() as driver_session:
                    # 获取所有关联的 session_id
                    get_sessions_query = """
                    MATCH (n:Novel {collection_name: $collection_name})-[:HAS_SESSION]->(s:Session)
                    RETURN s.uuid as session_id
                    """
                    result = await driver_session.run(get_sessions_query, collection_name=collection_name)
                    async for record in result:
                        session_ids.append(record["session_id"])
                    print(f"[INFO] 找到 {len(session_ids)} 个关联的 Session")
            except Exception as e:
                print(f"[WARNING] 获取 Session 列表失败: {e}")

        # 2. 删除 Zep 中的所有 session 数据（包括原始小说和分支）
        # 若 Novel/Session 关系缺失，兜底按 collection_name 删除，避免“前端看不到但后台仍在跑”
        zep_sessions_to_delete = list(dict.fromkeys(session_ids + [collection_name]))
        if client and zep_sessions_to_delete:
            deleted_session_count = 0
            for sid in zep_sessions_to_delete:
                try:
                    await client.memory.delete_memory(sid)
                    print(f"[INFO] Zep session {sid} 已删除")
                    deleted_session_count += 1
                except Exception as e:
                    print(f"[WARNING] 删除 Zep session {sid} 失败: {e}")
            deleted_sessions = deleted_session_count
        
        # 3. 删除 Neo4j 中的实体和关系
        if driver:
            try:
                async with driver.session() as driver_session:
                    # 删除 Session 节点（M2 平行宇宙）
                    session_query = """
                    MATCH (n:Novel {collection_name: $collection_name})-[:HAS_SESSION]->(s:Session)
                    DETACH DELETE s
                    """
                    await driver_session.run(session_query, collection_name=collection_name)

                    group_ids = list(dict.fromkeys(session_ids + [collection_name]))
                    # 第一步：删除所有 Entity 节点的关系（包括 outgoing 和 incoming）
                    edge_query = """
                    MATCH (n:Entity)
                    WHERE n.group_id IN $group_ids
                    MATCH (n)-[r]-(m)
                    DELETE r
                    RETURN count(r) as deleted
                    """
                    edge_result = await driver_session.run(edge_query, group_ids=group_ids)
                    edge_record = await edge_result.single()
                    if edge_record:
                        deleted_relationships = edge_record["deleted"]
                    
                    # 第二步：删除所有 Entity 节点
                    node_query = """
                    MATCH (n:Entity)
                    WHERE n.group_id IN $group_ids
                    DELETE n
                    RETURN count(n) as deleted
                    """
                    node_result = await driver_session.run(node_query, group_ids=group_ids)
                    node_record = await node_result.single()
                    if node_record:
                        deleted_entities = node_record["deleted"]
                    
                    # 第三步：删除 Novel 节点
                    novel_query = """
                    MATCH (n:Novel {collection_name: $collection_name})
                    DELETE n
                    RETURN count(n) as deleted
                    """
                    novel_result = await driver_session.run(novel_query, collection_name=collection_name)
                    novel_record = await novel_result.single()
                    if novel_record:
                        print(f"[INFO] 删除了 {novel_record['deleted']} 个 Novel 节点")
                    
                    # 第四步：清理孤立的 Episodic 节点（没有 Entity 连接的）
                    orphan_episodic_query = """
                    MATCH (e:Episodic)
                    WHERE NOT (e)-[]-(:Entity)
                    DELETE e
                    RETURN count(e) as deleted
                    """
                    orphan_result = await driver_session.run(orphan_episodic_query)
                    orphan_record = await orphan_result.single()
                    if orphan_record and orphan_record["deleted"] > 0:
                        print(f"[INFO] 清理了 {orphan_record['deleted']} 个孤立的 Episodic 节点")
                        
            except Exception as e:
                error_msg = f"Neo4j 删除失败: {str(e)}"
                errors.append(error_msg)
                print(f"[ERROR] {error_msg}")
        
        # 4. 通知 Graphiti 取消处理该小说的消息
        try:
            import httpx
            graphiti_url = os.getenv("GRAPHITI_API_URL", "http://localhost:8003")
            async with httpx.AsyncClient(timeout=5.0) as http_client:
                resp = await http_client.post(f"{graphiti_url}/cancel/{collection_name}")
                if resp.status_code == 200:
                    print(f"[INFO] Notified Graphiti to cancel processing for {collection_name}")
                else:
                    print(f"[WARNING] Failed to notify Graphiti: {resp.status_code}")
        except Exception as cancel_err:
            print(f"[WARNING] Could not notify Graphiti to cancel: {cancel_err}")
        
        # 5. 取消监控任务并从状态存储中移除
        if collection_name in status_store:
            task_info = status_store[collection_name]
            # 取消正在运行的监控任务
            monitor_task = task_info.get("_monitor_task")
            if monitor_task and not monitor_task.done():
                monitor_task.cancel()
                print(f"[INFO] Cancelled monitoring task for {collection_name}")
            del status_store[collection_name]
        # 6. 清理图谱缓存
        try:
            if graph_cache and isinstance(graph_cache, dict):
                items = graph_cache.get("items", {})
                if isinstance(items, dict):
                    items.pop(collection_name, None)
        except Exception:
            pass
        
        # 构建响应消息
        message_parts = []
        if deleted_sessions > 0:
            message_parts.append(f"删除了 {deleted_sessions} 个平行宇宙")
        if deleted_entities > 0:
            message_parts.append(f"删除了 {deleted_entities} 个实体")
        if deleted_relationships > 0:
            message_parts.append(f"删除了 {deleted_relationships} 个关系")
        
        if errors:
            if message_parts:
                message_parts.append(f"(部分删除失败)")
            else:
                message_parts.append("删除失败")
        else:
            if not message_parts:
                message_parts.append("删除成功")
        
        return DeleteResponse(
            collection_name=collection_name,
            success=len(errors) == 0,
            message="、".join(message_parts)
        )
        
    except Exception as e:
        return DeleteResponse(
            collection_name=collection_name,
            success=False,
            message=f"删除失败: {str(e)}"
        )





async def recover_novel_status(neo4j_driver, status_store: dict):
    """后端启动时恢复所有小说状态"""
    try:
        print("[INFO] 开始检查小说状态...")
        
        # 查询所有需要恢复的小说（processing/completed/extracting状态）
        async with neo4j_driver.session() as session:
            query = """
            MATCH (n:Novel)
            WHERE n.status IN ['processing', 'completed', 'extracting']
            RETURN n.collection_name as collection_name, n.title as title, n.status as status, n.created_at as created_at
            ORDER BY n.created_at DESC
            """
            result = await session.run(query)
            novels = [record async for record in result]
        
        if not novels:
            print("[INFO] 没有需要恢复的小说")
            return
        
        print(f"[INFO] 找到 {len(novels)} 个需要检查的小说")
        
        for novel in novels:
            collection_name = novel["collection_name"]
            title = novel["title"]
            current_status = novel["status"]
            created_at = novel["created_at"] or datetime.utcnow().isoformat()
            
            # 恢复路径先补齐内存状态，避免监控协程直接写入时报 KeyError
            status_store.setdefault(collection_name, {
                "status": current_status,
                "progress": 100.0 if current_status in ["completed", "extracting", "ready"] else 0.0,
                "chunks_processed": 0,
                "total_chunks": 0,
                "error_message": None,
                "created_at": created_at,
                "title": title or collection_name
            })
            
            print(f"[INFO] 检查: {title} (状态: {current_status})")
            
            # 检查Zep数据和实体数量
            zep_count = await check_zep_messages(collection_name)
            entity_count = await get_entity_count(collection_name, neo4j_driver)
            
            print(f"[DEBUG] Zep消息数: {zep_count}, 实体数: {entity_count}")
            
            if current_status == 'processing':
                # 处理中状态
                if zep_count > 0:
                    # Zep有数据，分块已完成
                    print(f"[INFO] {title}: 分块已完成，更新为completed并启动监控")
                    async with neo4j_driver.session() as update_session:
                        await update_session.run("""
                            MATCH (n:Novel {collection_name: $collection_name})
                            SET n.status = 'completed'
                        """, collection_name=collection_name)
                    status_store[collection_name]["status"] = "completed"
                    
                    # 启动实体提取监控并保存引用
                    monitor_task = asyncio.create_task(monitor_entity_extraction(
                        collection_name,
                        neo4j_driver,
                        status_store
                    ))
                    status_store[collection_name]["_monitor_task"] = monitor_task
                else:
                    # Zep无数据，分块失败
                    print(f"[WARNING] {title}: Zep无数据，标记为failed")
                    async with neo4j_driver.session() as update_session:
                        await update_session.run("""
                            MATCH (n:Novel {collection_name: $collection_name})
                            SET n.status = 'failed'
                        """, collection_name=collection_name)
                    status_store[collection_name]["status"] = "failed"
                    
            elif current_status in ['completed', 'extracting']:
                # 分块完成或提取中状态
                if entity_count == 0:
                    # 没有实体
                    if zep_count == 0:
                        # Zep也没数据，标记为failed
                        print(f"[WARNING] {title}: 无数据，标记为failed")
                        async with neo4j_driver.session() as update_session:
                            await update_session.run("""
                                MATCH (n:Novel {collection_name: $collection_name})
                                SET n.status = 'failed'
                            """, collection_name=collection_name)
                        status_store[collection_name]["status"] = "failed"
                    else:
                        # Zep有数据但无实体，可能还在提取中，启动监控
                        print(f"[INFO] {title}: Zep有数据但无实体，启动监控等待提取")
                        status_store[collection_name]["status"] = "extracting"
                        # 启动实体提取监控并保存引用
                        monitor_task = asyncio.create_task(monitor_entity_extraction(
                            collection_name,
                            neo4j_driver,
                            status_store
                        ))
                        status_store[collection_name]["_monitor_task"] = monitor_task
                else:
                    # 有实体，等待30秒观察
                    print(f"[INFO] {title}: 有实体，观察增长情况...")
                    final_count, is_stable = await observe_entity_growth(
                        collection_name,
                        neo4j_driver
                    )
                    
                    if is_stable and final_count > 0:
                        try:
                            dedup_stats = await deduplicate_entities_in_collection(collection_name, neo4j_driver)
                            if dedup_stats.get("removed_nodes", 0) > 0:
                                print(
                                    f"[INFO] {title}: Deduplicated entities "
                                    f"(groups={dedup_stats['merged_groups']}, removed={dedup_stats['removed_nodes']})"
                                )
                        except Exception as dedup_error:
                            print(f"[WARNING] {title}: Deduplication failed during recovery: {dedup_error}")

                        # 实体稳定，标记为ready
                        print(f"[INFO] {title}: 实体提取完成 ({final_count}个实体)")
                        async with neo4j_driver.session() as update_session:
                            await update_session.run("""
                                MATCH (n:Novel {collection_name: $collection_name})
                                SET n.status = 'ready'
                            """, collection_name=collection_name)
                        status_store[collection_name]["status"] = "ready"
                    else:
                        # 实体还在增长，重新启动监控
                        print(f"[INFO] {title}: 实体还在增长，重启监控任务")
                        async with neo4j_driver.session() as update_session:
                            await update_session.run("""
                                MATCH (n:Novel {collection_name: $collection_name})
                                SET n.status = 'extracting'
                            """, collection_name=collection_name)
                        status_store[collection_name]["status"] = "extracting"
                        
                        # 启动实体提取监控并保存引用
                        monitor_task = asyncio.create_task(monitor_entity_extraction(
                            collection_name,
                            neo4j_driver,
                            status_store
                        ))
                        status_store[collection_name]["_monitor_task"] = monitor_task
        
        print("[INFO] 小说状态检查完成")
        
    except Exception as e:
        print(f"[ERROR] 状态恢复失败: {e}")
