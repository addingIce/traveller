"""
小说上传和管理 API 端点
"""
import os
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


async def process_novel_task(
    collection_name: str,
    content: str,
    novel_title: str,
    client: AsyncZep,
    status_store: dict
) -> None:
    """
    异步处理小说内容
    这是后台任务，会更新 status_store 中的状态
    """
    try:
        # 更新状态：开始处理
        status_store[collection_name]["status"] = "processing"
        
        # 按双换行符分段
        chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 20]
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
    asyncio.create_task(process_novel_task(collection_name, text_content, novel_title, client, status_store))
    
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
    """
    status_store = getattr(request.app.state, "processing_tasks", {})
    
    novels = []
    for collection_name, task_info in status_store.items():
        # 获取实际的消息数量（如果已完成）
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
    
    if not client:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Zep 服务未就绪"
        )
    
    # 从状态存储中移除
    if collection_name in status_store:
        del status_store[collection_name]
    
    # 注意：Zep Python SDK 可能没有直接的删除 session API
    # 这里只是从状态存储中移除，实际数据保留
    # 未来如果需要完全删除，可能需要调用 Zep 的 HTTP API 或手动清理数据库
    
    # 注意：Neo4j 中的实体需要手动清理，这里暂不实现
    # 未来可以添加清理 Neo4j 数据的逻辑
    
    return DeleteResponse(
        collection_name=collection_name,
        success=True,
        message="小说已从列表中移除（注意：Zep 和 Neo4j 中的数据仍保留）"
    )