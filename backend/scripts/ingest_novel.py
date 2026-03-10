import os
import asyncio
from typing import List, Dict
from dotenv import load_dotenv
from zep_python import ZepClient
from zep_python.document import Document

# 加载环境变量
load_dotenv(dotenv_path="../.env")

ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

async def ingest_novel(file_path: str, collection_name: str, description: str):
    """
    将小说文件录入 Zep Document Collection
    """
    if not os.path.exists(file_path):
        print(f"错误: 文件 {file_path} 不存在")
        return

    print(f"正在读取小说: {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 简单的分段逻辑：按章节或固定字数 (这里模拟按双换行符分段)
    # 在生产环境中，这里建议使用更智能的 RecursiveCharacterTextSplitter
    chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 50]
    
    print(f"解析完成，共提取出 {len(chunks)} 个有效片段。")

    async with ZepClient(base_url=ZEP_API_URL, api_key=ZEP_API_KEY) as client:
        # 1. 创建或获取 Collection
        try:
            # 尝试获取，如果不存在则在异常中创建
            collection = await client.document.get_collection(collection_name)
            print(f"已找到现有集合: {collection_name}")
        except Exception:
            print(f"创建新集合: {collection_name}...")
            collection = await client.document.add_collection(
                name=collection_name,
                description=description,
                embedding_dimensions=1536, # OpenAI 默认维度
                is_auto_embedded=True      # 让 Zep 自动处理向量化
            )

        # 2. 转换为 Zep Document 对象并注入 Metadata
        documents = [
            Document(
                content=chunk,
                metadata={"source": file_path, "chunk_id": i, "novel": collection_name}
            )
            for i, chunk in enumerate(chunks)
        ]

        # 3. 批量写入 (Zep 支持高效批量操作)
        print(f"正在向 Zep 注入数据 (共 {len(documents)} 条)...")
        # 建议分批写入，防止大文件超时
        batch_size = 50
        for i in range(0, len(documents), batch_size):
            batch = documents[i:i + batch_size]
            uuids = await collection.add_documents(batch)
            print(f"已写入批次 {i//batch_size + 1}, 获得 UUIDs: {len(uuids)}个")

        print(f"✅ 录入完成！小说的向量库已就绪。")
        print(f"下一步建议：前往 Zep 查看辅助生成的知识图谱节点。")

if __name__ == "__main__":
    # 示例用法：python ingest_novel.py
    # 假设你在 data/novels/ 下有一本 test.txt
    novel_path = "../../data/novels/test.txt"
    asyncio.run(ingest_novel(
        file_path=novel_path,
        collection_name="test_novel",
        description="一本测试用的小说"
    ))
