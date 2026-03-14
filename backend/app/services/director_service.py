
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
        """精细化解析玩家意图：区分动作、对话和心理，并提取关键词"""
        # 1. 快捷指令处理
        if user_input.startswith("/act "):
            return {"action": user_input[5:].strip(), "dialogue": None, "thought": None, "metadata": {"manual": True}}
        if user_input.startswith("/say "):
            return {"action": None, "dialogue": user_input[5:].strip(), "thought": None, "metadata": {"manual": True}}

        # 2. LLM 解析
        system_prompt = """
        你是一位中立的剧情意图分析师。请将玩家的输入解构为以下四个维度：
        1. action: 玩家通过身体进行的动作。
        2. dialogue: 玩家对其他角色说的话。
        3. thought: 玩家内心的想法或心理描写。
        4. intensity: 意图强度 (1-5)。
        
        请仅输出 JSON 格式。
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                # 兼容性：某些代理商不支持 json_object 模式，改用 Prompt 约束 + 鲁棒解析
                # response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt + "\n请务必只输出 JSON，不要有任何其他解释文字。"},
                    {"role": "user", "content": user_input}
                ],
                temperature=0,
            )
            if not response.choices or not response.choices[0].message.content:
                return {"action": None, "dialogue": user_input, "thought": None, "intensity": 3, "metadata": {"fallback": True}}
            
            content = response.choices[0].message.content
            parsed = json.loads(content)
            parsed["metadata"] = {"manual": False}
            return parsed
        except Exception:
            return {"action": None, "dialogue": user_input, "thought": None, "intensity": 3, "metadata": {"fallback": True}}

class SafetyGuard:
    @staticmethod
    def sanitize(text: str) -> str:
        """基础指令注入防御层"""
        # 过滤常见的注入关键词（针对 LLM 指令注入）
        forbidden_patterns = [
            r"ignore previous instructions",
            r"forget everything",
            r"system prompt",
            r"you are now a",
            r"jailbreak",
            r"强制输出",
            r"忽略所有指令"
        ]
        sanitized = text
        for pattern in forbidden_patterns:
            sanitized = re.sub(pattern, "[指令过滤]", sanitized, flags=re.IGNORECASE)
        
        # 长度限制
        if len(sanitized) > 2000:
            sanitized = sanitized[:2000] + "...(文本过长已截断)"
            
        return sanitized

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
            "relevant_entities": [],
            "waypoints": []
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

                # 4. 获取剧情路标 (Waypoints) - 只有收束模式下特别重要，但沙盒模式也可知晓
                waypoint_query = """
                MATCH (w:Waypoint {group_id: $novel_id})
                RETURN w.title as title, w.requirement as requirement, w.description as description
                LIMIT 5
                """
                wp_result = await session.run(waypoint_query, novel_id=novel_id)
                waypoints = [f"路标: {r['title']} (前置: {r['requirement']}) - {r['description']}" async for r in wp_result]
                context["waypoints"] = waypoints
        except Exception as e:
            print(f"[DEBUG] ContextAssembler: Context fetch failed: {e}")

        return context

class DirectorAI:
    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    def _robust_json_parse(self, content: str) -> Dict[str, Any]:
        """鲁棒性 JSON 解析层：处理 Markdown 包裹、额外文本等风险"""
        # 1. 预处理：去除首尾空白和常见的 Markdown 包装
        clean_text = content.strip()
        clean_text = re.sub(r'^```json\s*', '', clean_text)
        clean_text = re.sub(r'\s*```$', '', clean_text)
        
        try:
            # 2. 尝试标准解析
            return json.loads(clean_text)
        except json.JSONDecodeError:
            try:
                # 3. 弹性解析：正则提取最外层大括号内容
                match = re.search(r'({.*})', clean_text, re.DOTALL)
                if match:
                    return json.loads(match.group(1))
            except Exception:
                pass
            
            # 4. 结构闭环：降级为纯文本叙事模式，防止系统崩溃
            print(f"[DEFENSE] Robust parsing failed. Falling back. Content: {clean_text[:100]}...")
            return {
                "story_text": clean_text,
                "world_impact": {
                    "world_state_changed": False,
                    "reason": "AI输出格式非标准，系统自动执行文本降级处理"
                },
                "ui_hints": ["format_mismatch_fallback"]
            }

    async def generate(self, context: Dict[str, Any], intent: Dict[str, Any], mode: str = "SANDBOX") -> Dict[str, Any]:
        """导演推演逻辑"""
        
        mode_instruction = ""
        if mode == "SANDBOX":
            mode_instruction = "沙盒模式：极高自由度，NPC 反应要根据其性格和世界逻辑自然演化，不强行引导剧情。"
        else:
            mode_instruction = "收束模式：在符合逻辑的前提下，尽可能引导玩家接触主线剧情或设定的关键路标。"

        system_prompt = f"""
        # Role: 穿越者引擎导演 (Director AI)
        
        ## Mode: {mode_instruction}
        
        ## Context:
        - 世界背景: {context['world_background']}
        - 起始点: {context.get('start_chapter_id', '开篇')}
        - 关键实体: {"; ".join(context['relevant_entities'])}
        - 剧情路标 (Waypoints): {"; ".join(context['waypoints'])}
        - 历史摘要: {context['session_summary']}
        
        ## Joint Output Protocol (JOP) - JSON Schema:
        请严格按以下 JSON 结构输出，不要包含任何 Markdown 格式以外的解释文字：
        {{
            "story_text": "高质量剧情叙述。在收束模式下，应尽可能引导玩家接近路标。",
            "world_impact": {{ 
                "world_state_changed": true/false, 
                "reason": "简述世界逻辑或NPC态度的变化" 
            }},
            "user_intent_summary": {{
                "action": "解析出的玩家肢体动作",
                "dialogue": "解析出的玩家发言内容",
                "thought": "解析出的玩家内心独白"
            }},
            "ui_hints": ["需前端高亮的关键词", "建议操作指令"]
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
                # 兼容性：某些代理商不支持 json_object 模式，改用 Prompt 约束 + 鲁棒解析
                # response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt + "\n请严格遵守 JSON 格式输出。"},
                    {"role": "user", "content": user_content}
                ],
                temperature=0.7,
            )
            if not response.choices or not response.choices[0].message.content:
                 raise ValueError("LLM 响应无效或 choices 为空")
                 
            content = response.choices[0].message.content
            return self._robust_json_parse(content)
        except Exception as e:
            print(f"[ERROR] DirectorAI generation failed: {e}")
            return {
                "story_text": "（时空发生扰动，剧情推演暂时中断，请重新尝试引导……）",
                "world_impact": {"world_state_changed": False, "reason": str(e)},
                "ui_hints": ["system_error"]
            }
