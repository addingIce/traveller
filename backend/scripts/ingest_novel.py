import os
import asyncio
from dotenv import load_dotenv
from zep_python.client import AsyncZep
from zep_python import Message

# 加载环境变量
load_dotenv(dotenv_path="../.env")

ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

async def ingest_novel(file_path: str, session_id: str):
    """
    将小说文件通过 Session Memory 方式录入 Zep CE (v2 SDK)
    """
    if not os.path.exists(file_path):
        print(f"错误: 文件 {file_path} 不存在")
        return

    print(f"正在读取小说: {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 按双换行符分段
    chunks = [c.strip() for c in content.split("\n\n") if len(c.strip()) > 20]
    print(f"解析完成，共提取出 {len(chunks)} 个有效片段。")

    client = AsyncZep(base_url=ZEP_API_URL, api_key=ZEP_API_KEY)

    # 1. 创建或获取 Session
    try:
        session = await client.memory.get_session(session_id)
        print(f"已找到现有 Session: {session_id}")
    except Exception:
        print(f"创建新 Session: {session_id}...")
        await client.memory.add_session(
            session_id=session_id,
            metadata={"type": "novel_ingest", "source": file_path}
        )

    # 2. 将小说片段逐批作为 Message 写入 Session Memory
    batch_size = 2 # 进一步减小批次，防止 Zep 过载
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
        
        retries = 3
        while retries > 0:
            try:
                await client.memory.add(session_id, messages=messages)
                print(f"  ✅ 已写入批次 {i // batch_size + 1}/{(len(chunks) - 1) // batch_size + 1} ({len(batch)} 条消息)")
                await asyncio.sleep(2) # 强制休眠，给 Zep 后台处理缓冲时间
                break
            except Exception as e:
                print(f"  ❌ 批次 {i // batch_size + 1} 写入失败: {e}. 正在重试 ({retries}/3)...")
                retries -= 1
                await asyncio.sleep(5)
                if retries == 0:
                    print(f"  🔥 批次 {i // batch_size + 1} 彻底失败，跳过。")

    print(f"\n🎉 试图通过稳健模式录入完成。")
    print(f"Zep 将在后台自动提取 Facts（事实）和 Summary（摘要）。")

    # 3. 验证写入结果
    await asyncio.sleep(3)
    try:
        memory = await client.memory.get(session_id)
        print(f"\n📊 验证结果:")
        print(f"  - 消息总数: {len(memory.messages) if memory.messages else 0}")
        if memory.summary:
            print(f"  - 自动摘要: {memory.summary.content[:300]}...")
        if memory.relevant_facts:
            print(f"  - 提取 Facts 数量: {len(memory.relevant_facts)}")
            for fact in memory.relevant_facts[:5]:
                print(f"    → {fact.fact}")
        else:
            print(f"  - Facts: Zep 正在后台生成中，请稍后再查...")
    except Exception as e:
        print(f"  验证时出现异常 (可忽略): {e}")

if __name__ == "__main__":
    novel_path = "../../data/novels/test.txt"
    asyncio.run(ingest_novel(
        file_path=novel_path,
        session_id="novel_test_novel"
    ))
