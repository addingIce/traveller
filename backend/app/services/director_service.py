
import os
import json
import re
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from zep_python import Message

class ActionParser:
    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def parse_intent(self, user_input: str) -> Dict[str, Any]:
        """解析玩家意图：区分动作、对话和心理"""
        # 如果是快捷指令格式如 /act 砍向敌人
        if user_input.startswith("/act "):
            return {"action": user_input[5:].strip(), "dialogue": None, "thought": None}
        if user_input.startswith("/say "):
            return {"action": None, "dialogue": user_input[5:].strip(), "thought": None}
        if user_input.startswith("/think "):
            return {"action": None, "dialogue": None, "thought": user_input[7:].strip()}

        # 否则使用大模型进行自然语言解析
        system_prompt = """
        你是一位中立的剧情解析助手。请将玩家的输入解构为：动作(action)、对话(dialogue)、心理描写(thought)。
        请仅输出 JSON 格式。
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input}
                ],
                temperature=0,
            )
            content = response.choices[0].message.content
            # Clean possible markdown wrap
            content = re.sub(r'^```json\s*|\s*```$', '', content.strip(), flags=re.MULTILINE)
            return json.loads(content)
        except Exception:
            # 回退：默认为对话
            return {"action": None, "dialogue": user_input, "thought": None}

class ContextAssembler:
    def __init__(self, zep_client, neo4j_driver):
        self.zep = zep_client
        self.neo4j = neo4j_driver

    async def assemble(self, session_id: str, novel_id: str) -> Dict[str, Any]:
        """组装全量上下文：玩家记忆 + 小说背景 + 实体逻辑"""
        context = {
            "session_history": "",
            "session_summary": "",
            "world_background": "",
            "relevant_entities": []
        }

        # 0. Fetch Session Metadata for Branching Context
        start_chapter_content = ""
        try:
            # Get session info to check for start_chapter_id
            session_info = await self.zep.memory.get_session(session_id)
            if session_info and session_info.metadata:
                start_ch_id = session_info.metadata.get("start_chapter_id")
                if start_ch_id:
                    # In this system, chapters are messages in the 'novel_{novel_id}' session
                    novel_sess_id = novel_id if novel_id.startswith("novel_") else f"novel_{novel_id}"
                    # We might need to fetch the specific message. 
                    # For simplicity, we'll note it in the context.
                    context["start_chapter_id"] = start_ch_id
        except Exception as e:
            print(f"[DEBUG] ContextAssembler: Session metadata fetch failed: {e}")

        # 1. 获取当前玩家 Session 的记忆
        try:
            memory = await self.zep.memory.get(session_id)
            context["session_history"] = "\n".join([f"{m.role}: {m.content}" for m in memory.messages[-10:]])
            context["session_summary"] = memory.summary.content if memory.summary else ""
        except Exception as e:
            print(f"[DEBUG] ContextAssembler: Session memory fetch failed: {e}")

        # 2. 获取小说本身的宏观背景（从 Zep 的 novel_id 集合获取摘要）
        try:
            # 小说的 content 存储在以 novel_id 为 session_id 的 Zep memory 中
            novel_memory = await self.zep.memory.get(novel_id)
            context["world_background"] = novel_memory.summary.content if novel_memory.summary else "暂无背景摘要"
            
            # 如果没有摘要，尝试拿前几条消息作为背景
            if not context["world_background"] and novel_memory.messages:
                 context["world_background"] = novel_memory.messages[0].content[:500] + "..."
        except Exception as e:
            print(f"[DEBUG] ContextAssembler: Novel background fetch failed: {e}")

        try:
            async with self.neo4j.session() as session:
                query = """
                MATCH (e:Entity {group_id: $novel_id})
                RETURN e.name as name, e.summary as summary
                LIMIT 10
                """
                result = await session.run(query, novel_id=novel_id)
                entities = [f"{r['name']}: {r['summary']}" async for r in result]
                context["relevant_entities"] = entities
        except Exception as e:
            print(f"[DEBUG] ContextAssembler: Entity fetch failed: {e}")

        return context

class DirectorAI:
    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def generate(self, context: Dict[str, Any], intent: Dict[str, Any], mode: str = "SANDBOX") -> Dict[str, Any]:
        """导演推演逻辑"""
        
        mode_instruction = ""
        if mode == "SANDBOX":
            mode_instruction = "沙盒模式：极高自由度，NPC 反应要根据其性格和世界逻辑自然演化，不强行引导剧情。"
        else:
            mode_instruction = "收束模式：在符合逻辑的前提下，尽可能引导玩家接触主线剧情或设定的关键路标。"

        system_prompt = f"""
        你是一位顶级小说家兼AI剧情推演导演（Director AI）。
        
        [当前模式]: {mode_instruction}
        
        [小说宏观背景]: {context['world_background']}
        
        {f"[平行宇宙起始章节]: {context.get('start_chapter_id', '小说开篇')}" if context.get('start_chapter_id') else ""}
        
        [已知实体设定]:
        {chr(10).join(context['relevant_entities'])}
        
        [本时间线历史摘录]: {context['session_summary']}
        
        请根据上下文和玩家意图进行推演。
        输出 JSON 格式：
        {{
            "story_text": "剧情文字描述",
            "world_impact": {{ "world_state_changed": bool, "reason": "原因" }},
            "ui_hints": []
        }}
        """

        user_content = f"""
        近期历史:
        {context['session_history']}
        
        玩家意图:
        动作: {intent.get('action') or '无'}
        对话: {intent.get('dialogue') or '无'}
        心理: {intent.get('thought') or '无'}
        """

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.7,
            )
            content = response.choices[0].message.content
            # Clean possible markdown wrap
            content = re.sub(r'^```json\s*|\s*```$', '', content.strip(), flags=re.MULTILINE)
            return json.loads(content)
        except Exception as e:
            print(f"[ERROR] DirectorAI generation failed: {e}")
            return {
                "story_text": "（推演中出现了一点波折，请稍后再试……）",
                "world_impact": {"world_state_changed": False, "reason": "系统推演异常"},
                "ui_hints": []
            }
