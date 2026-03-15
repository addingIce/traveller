import os
import json
import re
from datetime import datetime
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import AsyncOpenAI
from zep_python import Message

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-4o")
MODEL_PARSER = os.getenv("MODEL_PARSER", "gpt-4o-mini")

from app.services.director_service import ActionParser, ContextAssembler, DirectorAI
from app.models.schemas import ChatRequest, ChatResponse, DirectorMode

# 延迟初始化客户端以确保环境变量已加载
def get_aclient():
    key = os.getenv("OPENAI_API_KEY", "")
    url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    return AsyncOpenAI(api_key=key, base_url=url)

@router.post("/interact", response_model=ChatResponse)
async def chat_interact(req: ChatRequest, request: Request):
    """
    核心 API: 与导演模型进行互动，支持双轨模式 (沙盒/收束)。
    """
    try:
        zep = request.app.state.zep
        neo4j = request.app.state.neo4j_driver
        if not zep or not neo4j:
            raise HTTPException(status_code=503, detail="基础服务未就绪")
        
        # 1. 初始化组件
        aclient = get_aclient()
        parser = ActionParser(aclient, MODEL_PARSER)
        assembler = ContextAssembler(zep, neo4j)
        director = DirectorAI(aclient, MODEL_DIRECTOR)
        from app.services.director_service import SafetyGuard

        # 2. 解析意图 (Action Parsing)
        sanitized_message = SafetyGuard.sanitize(req.message)
        intent = await parser.parse_intent(sanitized_message)
        
        # 3. 装配上下文 (Context Assembly)
        context = await assembler.assemble(req.session_id, req.novel_id)

        # 4. 生成剧情 (Story Generation)
        ai_data = await director.generate(context, intent, req.mode or DirectorMode.SANDBOX)
        
        # 5. 回填意图摘要 (保持向后兼容)
        ai_data["user_intent_summary"] = intent
        
        # 5.1 异常回收日志
        try:
            ui_hints = ai_data.get("ui_hints", []) or []
            if "format_mismatch_fallback" in ui_hints:
                print(f"[WARNING] Director output format mismatch fallback: session={req.session_id}")
            if "system_error" in ui_hints:
                print(f"[ERROR] Director system error fallback: session={req.session_id}")
        except Exception:
            pass

        # 6. 将玩家输入和 AI 响应存入 Zep
        user_msg = Message(role="user", role_type="user", content=req.message)
        ai_msg = Message(role="assistant", role_type="assistant", content=ai_data["story_text"])
        await zep.memory.add(req.session_id, messages=[user_msg, ai_msg])

        # 7. 更新 Neo4j：会话时间 + 路标达成记录 (M3)
        try:
            async with neo4j.session() as session:
                # 更新交互时间
                await session.run(
                    "MATCH (s:Session {uuid: $sid}) SET s.last_interaction_at = $now",
                    sid=req.session_id, now=datetime.utcnow().isoformat()
                )
                
                # 持久化已达成的路标
                reached = ai_data.get("reached_waypoints", [])
                if isinstance(reached, list) and len(reached) > 0:
                    print(f"[PROGRESS] Session {req.session_id} reached waypoints: {reached}")
                    await session.run(
                        """
                        MATCH (s:Session {uuid: $sid})
                        MATCH (w:Waypoint {group_id: $gid})
                        WHERE w.title IN $reached
                        MERGE (s)-[:TRIGGERED {at: $now}]->(w)
                        """,
                        sid=req.session_id, gid=req.novel_id, 
                        reached=reached, now=datetime.utcnow().isoformat()
                    )
        except Exception as ne:
            print(f"[ERROR] Session state persistence failed: {ne}")

        # 8. 图谱缓存脏标记
        if ai_data.get("world_impact", {}).get("world_state_changed"):
            cache = request.app.state.graph_cache.get("items", {})
            item = cache.get(req.novel_id) or {}
            item["dirty"] = True
            cache[req.novel_id] = item

        return ChatResponse(**ai_data)

    except Exception as e:
        print(f"[ERROR] Chat Interact Failed: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"AI导演推演失败: {str(e)}")
