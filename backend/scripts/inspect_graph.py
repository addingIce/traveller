import os
import asyncio
from zep_python import ZepClient

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(dotenv_path="../.env")

ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

async def inspect_knowledge_graph(collection_name: str):
    """
    查看 Zep 自动为小说提取出的知识图谱
    """
    print(f"📡 正在尝试连接 Zep 获取图谱: {collection_name}...")
    
    async with ZepClient(base_url=ZEP_API_URL, api_key=ZEP_API_KEY) as client:
        # 获取集合中的统计数据
        try:
            collection = await client.document.get_collection(collection_name)
            doc_count = await collection.get_document_count()
            print(f"📊 集合状态: 已存储 {doc_count} 个文档片段")
            
            # 使用 Zep 的 Graph 查询（简单示例）
            # 获取最近提取的人物、实体及其关系
            graph_data = await client.graph.get_graph(collection_name)
            
            # 由于图谱是异步生成的，初始可能为空
            if not graph_data or not graph_data.nodes:
                print("⚠️ 提示: 知识图谱尚在异步提取中 (或尚未触发提取)。")
                print("请确保已开启 ZEP_NLP_OPENAI_API_KEY 或尝试等待 10-30 秒后再次运行。")
            else:
                print(f"✅ 已找到 {len(graph_data.nodes)} 个图谱节点和 {len(graph_data.edges)} 条关系线！")
                for node in graph_data.nodes:
                    print(f" - [Node] {node.name} ({node.type})")
                    for edge in graph_data.edges:
                        if edge.source == node.name:
                            print(f"   --> [{edge.label}] --> {edge.target}")

        except Exception as e:
            print(f"❌ 获取图谱失败: {str(e)}")

if __name__ == "__main__":
    # 使用方式: python inspect_graph.py
    collection_name = "test_novel"
    asyncio.run(inspect_knowledge_graph(collection_name))
