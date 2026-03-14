import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from dotenv import load_dotenv
from zep_python.client import AsyncZep
from neo4j import GraphDatabase, AsyncGraphDatabase

# 加载环境变量
load_dotenv()

ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

# 禁用网络代理以确保本地连接成功
os.environ["NO_PROXY"] = "localhost,127.0.0.1"
if "http_proxy" in os.environ: del os.environ["http_proxy"]
if "https_proxy" in os.environ: del os.environ["https_proxy"]
if "all_proxy" in os.environ: del os.environ["all_proxy"]

# OpenAI 兼容接口配置
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

# 分职责模型配置
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-4o")
MODEL_PARSER = os.getenv("MODEL_PARSER", "gpt-4o-mini")

# Neo4j 配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password123")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时执行
    try:
        # 创建 AsyncZep 客户端，增加超时配置
        app.state.zep = AsyncZep(
            base_url=ZEP_API_URL, 
            api_key=ZEP_API_KEY,
            # 增加超时时间
            timeout=300.0  # 5分钟超时
        )
        # 简易图谱缓存：按 collection 维护数据、脏标记和更新时间
        app.state.graph_cache = {
            "items": {},
            "ttl_seconds": 300,
            "boot_time": int(time.time()),
        }
        print("Zep 服务初步连接成功！")
        
        # 初始化小说处理任务状态存储
        app.state.processing_tasks = {}
        print("小说处理任务状态存储初始化完成！")
        
        # 初始化 Neo4j
        print(f"正在连接 Neo4j 服务：{NEO4J_URI}...")
        app.state.neo4j_driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        await app.state.neo4j_driver.verify_connectivity()
        print("Neo4j 服务连接成功！")
        
        # 恢复小说状态
        print("开始恢复小说状态...")
        from app.api.endpoints.novels import recover_novel_status
        await recover_novel_status(app.state.neo4j_driver, app.state.processing_tasks)
        print("小说状态恢复完成！")

    except Exception as e:
        print(f"后端基础设施连接失败警告: {str(e)}")
        app.state.zep = None
        app.state.neo4j_driver = None
        app.state.graph_cache = {
            "items": {},
            "ttl_seconds": 300,
            "boot_time": int(time.time()),
        }
        app.state.processing_tasks = {}
    yield
    # 关闭时执行
    zep_client = getattr(app.state, "zep", None)
    if zep_client and hasattr(zep_client, "close"):
        await zep_client.close()
    if getattr(app.state, "neo4j_driver", None):
        await app.state.neo4j_driver.close()

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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8080, reload=True)
