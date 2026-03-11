import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
from zep_python.client import AsyncZep

# 加载环境变量
load_dotenv()

ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

# OpenAI 兼容接口配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# 分职责模型配置
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-4o")
MODEL_PARSER = os.getenv("MODEL_PARSER", "gpt-4o-mini")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    print(f"正在连接 Zep 服务：{ZEP_API_URL}...")
    try:
        # 在真实生产中这里会进行一次健康检查
        app.state.zep = AsyncZep(base_url=ZEP_API_URL, api_key=ZEP_API_KEY)
        # 简易图谱缓存：按 collection 维护数据、脏标记和更新时间
        app.state.graph_cache = {
            "items": {},
            "ttl_seconds": 300,
            "boot_time": int(time.time()),
        }
        print("Zep 服务初步连接成功！")
    except Exception as e:
        print(f"Zep 服务连接失败警告: {str(e)}")
        app.state.zep = None
        app.state.graph_cache = {
            "items": {},
            "ttl_seconds": 300,
            "boot_time": int(time.time()),
        }
    yield
    # 关闭时执行
    if getattr(app.state, "zep", None):
        await app.state.zep.close()

from app.api.endpoints import api_router

app = FastAPI(
    title="穿越者引擎 (Traveller Engine) API",
    version="0.1.0",
    description="基于 Zep 和 LLM 的小说解析与互动叙事引擎后端",
    lifespan=lifespan
)

app.include_router(api_router, prefix="/api/v1")

@app.get("/")
async def root():
    return {
        "project": "Traveller Engine",
        "status": "online",
        "milestone": "M1-Week1",
        "zep_connection": "initialized"
    }

@app.get("/health")
async def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8080, reload=True)
