from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import os
import yaml
from pathlib import Path

router = APIRouter()

# 配置文件路径
CONFIG_FILE = Path(__file__).parent.parent.parent / "config.yaml"
DOCKER_COMPOSE_FILE = Path(__file__).parent.parent.parent.parent / "docker-compose.yml"
ENV_FILE = Path(__file__).parent.parent.parent.parent / ".env"

# 配置数据模型
class PerformanceConfig(BaseModel):
    """性能配置"""
    graphiti_llm_max_concurrency: int = 1
    graphiti_llm_min_interval: float = 0.5
    batch_size: int = 2
    batch_delay: float = 1.0
    poll_interval: int = 5
    status_poll_interval: int = 3

class BusinessConfig(BaseModel):
    """业务配置"""
    max_file_size_mb: int = 10
    chunk_min_length: int = 100
    chunk_max_length: int = 500
    zep_timeout: int = 300
    neo4j_timeout: int = 30

class APIConfig(BaseModel):
    """API 配置"""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o"
    model_director: str = "gpt-4o"  # 导演模型（剧情推演）
    model_parser: str = "gpt-4o-mini"  # 解析模型（意图分析）
    model_zep_extractor: str = "gpt-4o-mini"  # Zep 提取模型（知识图谱）
    model_graphiti: str = "gpt-4o"  # Graphiti 模型（实体提取）
    embedding_api_key: str = ""
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v4"

class SystemConfig(BaseModel):
    """系统配置"""
    performance: PerformanceConfig = PerformanceConfig()
    business: BusinessConfig = BusinessConfig()
    api: APIConfig = APIConfig()

# 内存中的配置（运行时配置）
runtime_config = SystemConfig()

def load_config_from_file() -> SystemConfig:
    """从配置文件加载配置"""
    global runtime_config
    
    # 如果配置文件存在，从文件加载
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
                if config_data:
                    runtime_config = SystemConfig(**config_data)
                    return runtime_config
        except Exception as e:
            print(f"[ERROR] Failed to load config file: {e}")
    
    # 否则从环境变量和默认值加载
    load_config_from_env()
    return runtime_config

def load_config_from_env():
    """从环境变量加载配置"""
    global runtime_config
    
    # 性能参数
    runtime_config.performance.graphiti_llm_max_concurrency = int(os.getenv("GRAPHITI_LLM_MAX_CONCURRENCY", "1"))
    runtime_config.performance.graphiti_llm_min_interval = float(os.getenv("GRAPHITI_LLM_MIN_INTERVAL", "0.5"))
    runtime_config.performance.batch_size = int(os.getenv("BATCH_SIZE", "2"))
    runtime_config.performance.batch_delay = float(os.getenv("BATCH_DELAY", "1.0"))
    runtime_config.performance.poll_interval = int(os.getenv("POLL_INTERVAL", "5"))
    runtime_config.performance.status_poll_interval = int(os.getenv("STATUS_POLL_INTERVAL", "3"))
    
    # 业务参数
    runtime_config.business.max_file_size_mb = int(os.getenv("MAX_FILE_SIZE_MB", "10"))
    runtime_config.business.chunk_min_length = int(os.getenv("CHUNK_MIN_LENGTH", "100"))
    runtime_config.business.chunk_max_length = int(os.getenv("CHUNK_MAX_LENGTH", "500"))
    runtime_config.business.zep_timeout = int(os.getenv("ZEP_TIMEOUT", "300"))
    runtime_config.business.neo4j_timeout = int(os.getenv("NEO4J_TIMEOUT", "30"))
    
    # API 配置
    runtime_config.api.llm_api_key = os.getenv("OPENAI_API_KEY", "")
    runtime_config.api.llm_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    runtime_config.api.llm_model = os.getenv("MODEL_DIRECTOR", "gpt-4o")
    runtime_config.api.embedding_api_key = os.getenv("EMBEDDING_OPENAI_API_KEY", "")
    runtime_config.api.embedding_base_url = os.getenv("EMBEDDING_OPENAI_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    runtime_config.api.embedding_model = os.getenv("EMBEDDING_MODEL_NAME", "text-embedding-v4")

def save_config_to_file(config: SystemConfig):
    """保存配置到文件"""
    try:
        config_data = config.model_dump()
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)
        print(f"[INFO] Config saved to {CONFIG_FILE}")
    except Exception as e:
        print(f"[ERROR] Failed to save config file: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save config: {str(e)}")

def update_env_file(config: SystemConfig):
    """更新 .env 文件"""
    try:
        if not ENV_FILE.exists():
            # 创建 .env 文件
            with open(ENV_FILE, 'w', encoding='utf-8') as f:
                f.write("# Auto-generated config\n")
        
        # 读取现有内容
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 更新环境变量
        env_vars = {
            # LLM 配置
            "OPENAI_API_KEY": config.api.llm_api_key,
            "OPENAI_BASE_URL": config.api.llm_base_url,
            "MODEL_DIRECTOR": config.api.model_director,
            "MODEL_PARSER": config.api.model_parser,
            "MODEL_ZEP_EXTRACTOR": config.api.model_zep_extractor,
            "MODEL_NAME": config.api.model_graphiti,  # Graphiti 模型
            # Embedding 配置
            "EMBEDDING_OPENAI_API_KEY": config.api.embedding_api_key,
            "EMBEDDING_OPENAI_BASE_URL": config.api.embedding_base_url,
            "EMBEDDING_MODEL_NAME": config.api.embedding_model,
            # Zep NLP 配置
            "ZEP_NLP_OPENAI_API_KEY": config.api.llm_api_key,  # 使用相同的 API Key
            "ZEP_NLP_OPENAI_BASE_URL": config.api.llm_base_url,  # 使用相同的 Base URL
            "ZEP_NLP_OPENAI_MODEL": config.api.model_zep_extractor,  # 使用 Zep 提取模型
            # 性能配置
            "GRAPHITI_LLM_MAX_CONCURRENCY": str(config.performance.graphiti_llm_max_concurrency),
            "GRAPHITI_LLM_MIN_INTERVAL": str(config.performance.graphiti_llm_min_interval),
            "BATCH_SIZE": str(config.performance.batch_size),
            "BATCH_DELAY": str(config.performance.batch_delay),
            "POLL_INTERVAL": str(config.performance.poll_interval),
            "STATUS_POLL_INTERVAL": str(config.performance.status_poll_interval),
            # 业务配置
            "MAX_FILE_SIZE_MB": str(config.business.max_file_size_mb),
            "CHUNK_MIN_LENGTH": str(config.business.chunk_min_length),
            "CHUNK_MAX_LENGTH": str(config.business.chunk_max_length),
            "ZEP_TIMEOUT": str(config.business.zep_timeout),
            "NEO4J_TIMEOUT": str(config.business.neo4j_timeout),
        }
        
        # 更新或添加环境变量
        updated_lines = []
        updated_keys = set()
        
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key = line.split('=')[0].strip()
                if key in env_vars:
                    value = env_vars[key]
                    if value:  # 只保存非空的值
                        updated_lines.append(f"{key}={value}\n")
                    updated_keys.add(key)
                    continue
            updated_lines.append(line + '\n')
        
        # 添加缺失的环境变量
        for key, value in env_vars.items():
            if key not in updated_keys and value:
                updated_lines.append(f"{key}={value}\n")
        
        # 写回文件
        with open(ENV_FILE, 'w', encoding='utf-8') as f:
            f.writelines(updated_lines)
        
        print(f"[INFO] Updated .env file")
    except Exception as e:
        print(f"[ERROR] Failed to update .env file: {e}")

@router.get("/config", response_model=SystemConfig)
async def get_config():
    """获取当前系统配置"""
    return runtime_config

@router.post("/config", response_model=dict)
async def update_config(config: SystemConfig):
    """更新系统配置"""
    global runtime_config
    
    try:
        # 保存到配置文件
        save_config_to_file(config)
        
        # 更新 .env 文件（API Key 等）
        update_env_file(config)
        
        # 更新运行时配置
        runtime_config = config
        
        return {
            "success": True,
            "message": "配置已更新并保存"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config/reload")
async def reload_config():
    """重新加载配置"""
    try:
        global runtime_config
        runtime_config = load_config_from_file()
        return {
            "success": True,
            "message": "配置已重新加载",
            "config": runtime_config.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/config/reset")
async def reset_config():
    """重置配置为默认值"""
    global runtime_config
    runtime_config = SystemConfig()
    
    try:
        save_config_to_file(runtime_config)
        return {
            "success": True,
            "message": "配置已重置为默认值",
            "config": runtime_config.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/config/presets")
async def get_config_presets():
    """获取配置预设"""
    presets = {
        "default": {
            "name": "默认配置",
            "description": "适合大多数场景的平衡配置",
            "config": SystemConfig().model_dump()
        },
        "high_concurrency": {
            "name": "高并发模式",
            "description": "适合高并发 LLM，最大化处理速度",
            "config": {
                "performance": {
                    "graphiti_llm_max_concurrency": 10,
                    "graphiti_llm_min_interval": 0.1,
                    "batch_size": 10,
                    "batch_delay": 0.2,
                    "poll_interval": 2,
                    "status_poll_interval": 1
                },
                "business": SystemConfig().business.model_dump(),
                "api": SystemConfig().api.model_dump()
            }
        },
        "low_latency": {
            "name": "低延迟模式",
            "description": "优先考虑响应速度，适合小文件快速处理",
            "config": {
                "performance": {
                    "graphiti_llm_max_concurrency": 5,
                    "graphiti_llm_min_interval": 0.2,
                    "batch_size": 5,
                    "batch_delay": 0.5,
                    "poll_interval": 2,
                    "status_poll_interval": 1
                },
                "business": {
                    "max_file_size_mb": 5,
                    "chunk_min_length": 150,
                    "chunk_max_length": 800,
                    "zep_timeout": 180,
                    "neo4j_timeout": 20
                },
                "api": SystemConfig().api.model_dump()
            }
        }
    }
    return presets

@router.post("/config/restart")
async def restart_services():
    """重启 Docker 服务以使配置生效"""
    import subprocess
    
    try:
        # 执行 docker-compose restart
        result = subprocess.run(
            ["docker-compose", "restart"],
            cwd=str(DOCKER_COMPOSE_FILE.parent),
            capture_output=True,
            text=True,
            timeout=120
        )
        
        if result.returncode == 0:
            return {
                "success": True,
                "message": "Docker 服务重启成功",
                "output": result.stdout
            }
        else:
            raise HTTPException(
                status_code=500,
                detail=f"重启失败: {result.stderr}"
            )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail="重启超时，请手动检查服务状态"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"重启服务时出错: {str(e)}"
        )

@router.get("/config/services/status")
async def get_services_status():
    """获取 Docker 服务状态"""
    import subprocess
    
    try:
        result = subprocess.run(
            ["docker-compose", "ps"],
            cwd=str(DOCKER_COMPOSE_FILE.parent),
            capture_output=True,
            text=True,
            timeout=30
        )
        
        return {
            "success": True,
            "status": result.stdout
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"获取服务状态失败: {str(e)}"
        )

# 初始化时加载配置
try:
    load_config_from_file()
    print("[INFO] System config loaded successfully")
except Exception as e:
    print(f"[WARNING] Failed to load system config: {e}, using defaults")