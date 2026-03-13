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


class UploadResponse(BaseModel):
    """上传响应"""
    collection_name: str
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
    error_message: Optional[str] = None


class DeleteResponse(BaseModel):
    """删除响应"""
    collection_name: str
    success: bool
    message: str


class NovelsListResponse(BaseModel):
    """小说列表响应"""
    novels: List[NovelInfo]


# ========== 辅助函数 ==========

def generate_collection_name(title: str) -> str:
    """生成唯一的集合名称"""
    timestamp = int(time.time())
    # 使用标题的拼音或简单哈希作为标识
    import hashlib
    title_hash = hashlib.md5(title.encode()).hexdigest()[:8]
    return f"novel_{timestamp}_{title_hash}"


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


def smart_chunk_content(content: str, min_length: int = 100, max_length: int = 500) -> list[str]:
    """
    智能分段函数：
    - 优先在段落边界（双换行符）分割
    - 如果段落太短，与下一段合并
    - 如果段落太长，按句子强制分割
    """
    chunks = []
    
    # 先按双换行符分割成段落
    paragraphs = content.split("\n\n")
    current_chunk = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
            
        # 如果当前段落 + 当前chunk 不超过最大长度，合并
        if len(current_chunk) + len(para) + 2 <= max_length:
            current_chunk += (("\n\n" if current_chunk else "") + para)
        else:
            # 当前chunk已满，需要处理
            if len(current_chunk) >= min_length:
                chunks.append(current_chunk)
            
            # 如果单个段落超过最大长度，需要强制分割
            if len(para) > max_length:
                # 按句子分割
                sentences = re.split(r'[。！？\n]', para)
                temp_chunk = ""
                for sentence in sentences:
                    sentence = sentence.strip()
                    if not sentence:
                        continue
                    if len(temp_chunk) + len(sentence) + 1 <= max_length:
                        temp_chunk += (sentence + "。")
                    else:
                        if len(temp_chunk) >= min_length:
                            chunks.append(temp_chunk)
                        temp_chunk = sentence + "。"
                current_chunk = temp_chunk
            else:
                current_chunk = para
    
    # 处理最后一个chunk
    if len(current_chunk) >= min_length:
        chunks.append(current_chunk)
    
    return chunks


async def process_novel_task(
    collection_name: str,
    content: str,
    novel_title: str,
    client: AsyncZep,
    status_store: dict,
    neo4j_driver = None
) -> None:
    """
    异步处理小说内容
    这是后台任务，会更新 status_store 中的状态
    """
    try:
        # 更新状态：开始处理
        status_store[collection_name]["status"] = "processing"
        
        # 在 Neo4j 中创建 Novel 节点，存储小说元数据
        if neo4j_driver:
            try:
                async with neo4j_driver.session() as session:
                    # 创建 Novel 节点（如果不存在）
                    create_novel_query = """
                    MERGE (n:Novel {collection_name: $collection_name})
                    ON CREATE SET 
                        n.title = $title,
                        n.created_at = $created_at,
                        n.status = 'processing'
                    ON MATCH SET 
                        n.status = 'processing'
                    RETURN n
                    """
                    await session.run(
                        create_novel_query,
                        collection_name=collection_name,
                        title=novel_title,
                        created_at=status_store[collection_name]["created_at"]
                    )
                    print(f"[INFO] Created/Updated Novel node: {collection_name}")
            except Exception as e:
                print(f"[ERROR] Failed to create Novel node: {e}")
        
        # 使用智能分段策略
        chunks = smart_chunk_content(content, min_length=100, max_length=500)
        total_chunks = len(chunks)
        status_store[collection_name]["total_chunks"] = total_chunks
        
        # 创建或获取 Session
        try:
            print(f"[DEBUG] Getting or creating session: {collection_name}")
            session = await client.memory.get_session(collection_name)
            print(f"[DEBUG] Session found: {collection_name}")
        except Exception as e:
            print(f"[DEBUG] Session not found, creating new one: {e}")
            await client.memory.add_session(
                session_id=collection_name,
                metadata={"type": "novel_ingest", "source": novel_title}
            )
            print(f"[DEBUG] Session created: {collection_name}")
        
        # 批量写入 Zep memory
        batch_size = 2
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            messages = [
                Message(
                    role_type="user",
                    role="讲述者",
                    content=chunk,
                )
                for chunk in batch
            ]
            
            # 重试逻辑
            retries = 3
            while retries > 0:
                try:
                    print(f"[DEBUG] Writing batch {i // batch_size + 1}/{(len(chunks) - 1) // batch_size + 1} to Zep...")
                    await client.memory.add(collection_name, messages=messages)
                    print(f"[DEBUG] Batch {i // batch_size + 1} written successfully")
                    break
                except Exception as e:
                    print(f"[DEBUG] Batch {i // batch_size + 1} failed (retries left: {retries}): {e}")
                    retries -= 1
                    if retries == 0:
                        raise e
                    await asyncio.sleep(2)
            
            # 更新进度
            processed = min(i + batch_size, total_chunks)
            status_store[collection_name]["chunks_processed"] = processed
            status_store[collection_name]["progress"] = (processed / total_chunks) * 100
            
            # 给 Zep 缓冲时间
            await asyncio.sleep(1)
        
        # 更新状态：完成
        status_store[collection_name]["status"] = "completed"
        status_store[collection_name]["progress"] = 100.0
        
        # 更新 Neo4j 中 Novel 节点的状态
        if neo4j_driver:
            try:
                async with neo4j_driver.session() as session:
                    update_novel_query = """
                    MATCH (n:Novel {collection_name: $collection_name})
                    SET n.status = 'completed'
                    RETURN n
                    """
                    await session.run(update_novel_query, collection_name=collection_name)
                    print(f"[INFO] Updated Novel node status to 'completed': {collection_name}")
            except Exception as e:
                print(f"[ERROR] Failed to update Novel node status: {e}")
        
        # 注意：Graphiti 会由 Zep 自动触发，无需手动调用
        # Zep 配置了 graphiti.service_url，会自动提取实体和关系
        
    except Exception as e:
        # 更新状态：失败
        status_store[collection_name]["status"] = "failed"
        status_store[collection_name]["error_message"] = str(e)
        print(f"[ERROR] 小说处理失败 {collection_name}: {e}")


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
        "title": novel_title
    }
    
    # 启动异步处理任务
    asyncio.create_task(process_novel_task(collection_name, text_content, novel_title, client, status_store, neo4j_driver))
    
    # 预估处理时间（基于文件大小）
    chunks_count = len([c for c in text_content.split("\n\n") if len(c.strip()) > 20])
    estimated_time = max(10, chunks_count * 2)  # 每个片段约 2 秒
    
    return UploadResponse(
        collection_name=collection_name,
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
    
    # 优先从 Neo4j 获取所有有数据的小说
    if driver:
        try:
            async with driver.session() as session:
                # 获取所有 Novel 节点，以及每个小说的实体数量
                novel_query = """
                MATCH (novel:Novel)
                OPTIONAL MATCH (entity:Entity {group_id: novel.collection_name})
                WITH novel, COUNT(DISTINCT entity) as entity_count
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
                    chunks_count = task_info.get("chunks_processed", entity_count)
                    
                    novels.append(NovelInfo(
                        collection_name=collection_name,
                        title=novel_title,
                        status=status,
                        created_at=created_at,
                        chunks_count=chunks_count
                    ))
                
                # 获取没有 Novel 节点的旧小说（只有 Entity 节点）
                old_novels_query = """
                MATCH (e:Entity)
                WHERE e.group_id STARTS WITH 'novel_' 
                  AND NOT EXISTS { (:Novel {collection_name: e.group_id}) }
                RETURN DISTINCT e.group_id as group_id, COUNT(e) as entity_count
                ORDER BY group_id
                """
                result = await session.run(old_novels_query)
                async for record in result:
                    collection_name = record["group_id"]
                    entity_count = record["entity_count"]
                    
                    # 从 status_store 获取额外的元数据（如果有）
                    task_info = status_store.get(collection_name, {})
                    
                    novels.append(NovelInfo(
                        collection_name=collection_name,
                        title=task_info.get("title", collection_name),  # 使用 collection_name 作为标题
                        status=task_info.get("status", "completed"),
                        created_at=task_info.get("created_at", ""),
                        chunks_count=entity_count
                    ))
        except Exception as e:
            print(f"[ERROR] Failed to get novels from Neo4j: {e}")
    
    # 如果 Neo4j 查询失败或没有数据，回退到使用 status_store
    if not novels:
        for collection_name, task_info in status_store.items():
            chunks_count = task_info.get("chunks_processed", 0)
            
            novels.append(NovelInfo(
                collection_name=collection_name,
                title=task_info.get("title", collection_name),
                status=task_info.get("status", "unknown"),
                created_at=task_info.get("created_at", ""),
                chunks_count=chunks_count
            ))
    
    # 按创建时间倒序排列
    novels.sort(key=lambda x: x.created_at, reverse=True)
    
    return NovelsListResponse(novels=novels)


@router.get("/{collection_name}/status", response_model=ProcessStatusResponse)
async def get_novel_status(collection_name: str, request: Request):
    """
    获取指定小说的处理状态
    """
    status_store = getattr(request.app.state, "processing_tasks", {})
    
    if collection_name not in status_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="小说不存在"
        )
    
    task_info = status_store[collection_name]
    
    return ProcessStatusResponse(
        collection_name=collection_name,
        status=task_info.get("status", "unknown"),
        progress=task_info.get("progress", 0.0),
        chunks_processed=task_info.get("chunks_processed", 0),
        total_chunks=task_info.get("total_chunks", 0),
        error_message=task_info.get("error_message")
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
    errors = []
    
    try:
        # 1. 删除 Neo4j 中的实体和关系
        if driver:
            try:
                async with driver.session() as driver_session:
                    # 第一步：删除所有 Entity 节点的关系（包括 outgoing 和 incoming）
                    # 使用 DETACH DELETE 删除关系但不删除目标节点
                    edge_query = """
                    MATCH (n:Entity {group_id: $group_id})-[r]-(m)
                    DETACH DELETE r
                    RETURN count(r) as deleted
                    """
                    edge_result = await driver_session.run(edge_query, group_id=collection_name)
                    edge_record = await edge_result.single()
                    if edge_record:
                        deleted_relationships = edge_record["deleted"]
                    
                    # 第二步：删除所有 Entity 节点
                    node_query = """
                    MATCH (n:Entity {group_id: $group_id})
                    DELETE n
                    RETURN count(n) as deleted
                    """
                    node_result = await driver_session.run(node_query, group_id=collection_name)
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
        
        # 2. 尝试删除 Zep session（如果 API 支持）
        try:
            # Zep Python SDK 可能没有直接的删除方法
            # 这里尝试使用 HTTP API 删除 session
            import httpx
            zep_api_url = os.getenv("ZEP_API_URL", "http://localhost:8000")
            async with httpx.AsyncClient() as http_client:
                # 尝试删除 session
                response = await http_client.delete(
                    f"{zep_api_url}/sessions/{collection_name}"
                )
                if response.status_code == 200 or response.status_code == 204:
                    print(f"[INFO] Zep session {collection_name} 已删除")
                elif response.status_code == 404:
                    print(f"[INFO] Zep session {collection_name} 不存在")
                else:
                    print(f"[WARNING] Zep session 删除失败: {response.status_code}")
        except Exception as e:
            error_msg = f"Zep session 删除失败: {str(e)}"
            errors.append(error_msg)
            print(f"[WARNING] {error_msg}")
        
        # 3. 从状态存储中移除
        if collection_name in status_store:
            del status_store[collection_name]
        
        # 构建响应消息
        message_parts = []
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