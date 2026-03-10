import os
import json
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from openai import AsyncOpenAI
from zep_python import ZepClient
from zep_python.memory import Message

router = APIRouter()

# 获取全局环境变量
ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-4o")

# 初始化 OpenAI Async 客户端
aclient = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)

class ChatRequest(BaseModel):
    session_id: str
    collection_name: Optional[str] = "test_novel"  # 代表是在哪个小说所在的背景进行的游玩
    message: str

class IntentSummary(BaseModel):
    action: Optional[str] = None
    dialogue: Optional[str] = None
    thought: Optional[str] = None

class WorldImpact(BaseModel):
    world_state_changed: bool
    reason: Optional[str] = None

class ChatResponse(BaseModel):
    story_text: str
    user_intent_summary: IntentSummary
    world_impact: WorldImpact
    ui_hints: List[str]

@router.post("/interact", response_model=ChatResponse)
async def chat_interact(req: ChatRequest):
    """
    核心 API: 与导演模型进行互动并获取多态解构数据。
    """
    try:
        async with ZepClient(base_url=ZEP_API_URL, api_key=ZEP_API_KEY) as zep_client:
            
            # --- 1. 将玩家的输入推送到 Zep 记忆中 ---
            user_message = Message(role="user", content=req.message)
            await zep_client.memory.add_memory(req.session_id, [user_message])
            
            # --- 2. 尝试获取最近的记忆摘要和内容 ---
            try:
                memory = await zep_client.memory.get_memory(req.session_id)
                history = "\n".join([f"{m.role}: {m.content}" for m in memory.messages])
                summary = memory.summary.content if memory.summary else "暂无该时间线的摘要。"
            except Exception:
                history = ""
                summary = "这是新的开始。"
                
            # --- 3. [可选] 获取该小说的宏观背景图谱 (为了简便我们在此示例中通过 collection 获取静态说明)
            world_bible_prompt = f"你所在的世界发生于小说 {req.collection_name} 之内。请符合小说的逻辑设定。"
            
            # --- 4. 组装复杂的导演 Prompt (同步解构协议) ---
            system_prompt = f"""
            你是一位顶级小说家兼AI剧情推演导演（Director AI）。玩家处于第一人称视角。
            
            [当前世界背景]: {world_bible_prompt}
            [本时间线之前的故事摘要]: {summary}
            
            请根据下面的近期交互历史，以及玩家最新一轮的动作进行推演。
            请务必以合法的 JSON 格式进行响应输出。绝不能输出 markdown 代码块标记，只能输出纯 JSON 字符串。
            
            期望的 JSON 格式必须包含：
            {{
                "story_text": "由于玩家的动作，接下来发生的剧情文字描述（包含旁白、所有NPC的回应等），要富有文学性。",
                "user_intent_summary": {{
                    "action": "玩家刚刚动作的简短概括(如果是动作的话)",
                    "dialogue": "玩家说了什么话(如果没有留空)",
                    "thought": "玩家表达的心理暗示(如果没有留空)"
                }},
                "world_impact": {{
                    "world_state_changed": true/false, // 玩家刚刚的行为是否足以产生长远的影响或者蝴蝶效应？
                    "reason": "如果为true，简述为什么世界线发生变动了"
                }},
                "ui_hints": ["text_color_sky", "shake_screen"] // 为前端提供的特效提示数组，可随意留空
            }}
            """
            
            # --- 5. 呼叫大模型执行推理 ---
            response = await aclient.chat.completions.create(
                model=MODEL_DIRECTOR,
                response_format={ "type": "json_object" }, # 强制使用结构化输出
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"互动历史:\n{history}\n\n[玩家最新一回合输入]: {req.message}"}
                ],
                temperature=0.7
            )
            
            raw_json_str = response.choices[0].message.content
            
            # --- 6. 解析并包装返回结果 ---
            ai_data = json.loads(raw_json_str)
            
            # 将导演 AI 生成的剧情也作为一条 Message 推回 Zep，方便下一轮记忆
            ai_message = Message(role="assistant", content=ai_data.get("story_text", "……"))
            await zep_client.memory.add_memory(req.session_id, [ai_message])

            return ChatResponse(**ai_data)

    except Exception as e:
        print(f"Chat Interact Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"AI导演推演失败: {str(e)}")
