
import os
import json
import re
from typing import List, Dict, Any, Optional
from openai import AsyncOpenAI
from zep_python import Message
from app.services.session_service import SessionService

class ActionParser:
    def __init__(self, client: AsyncOpenAI, model: str):
        self.client = client
        self.model = model

    async def parse_intent(self, user_input: str) -> Dict[str, Any]:
        """精细化解析玩家意图：区分动作、对话和心理，并提取关键词"""
        # 1. 快捷指令处理
        if user_input.startswith("/act "):
            action_text = user_input[5:].strip()
            combat = bool(re.search(r"(攻击|战斗|施法|法术|挥剑|射击|格挡|冲刺|斩|刺|砍|踢|射箭|招式|技能)", action_text))
            return {"action": action_text, "dialogue": None, "thought": None, "metadata": {"manual": True, "combat": combat}}
        if user_input.startswith("/say "):
            return {"action": None, "dialogue": user_input[5:].strip(), "thought": None, "metadata": {"manual": True, "combat": False}}

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
            action_text = (parsed.get("action") or "").strip()
            combat = bool(re.search(r"(攻击|战斗|施法|法术|挥剑|射击|格挡|冲刺|斩|刺|砍|踢|射箭|招式|技能)", action_text))
            parsed["metadata"] = {"manual": False, "combat": combat}
            return parsed
        except Exception:
            return {"action": None, "dialogue": user_input, "thought": None, "intensity": 3, "metadata": {"fallback": True, "combat": False}}

class SafetyGuard:
    """指令注入防御层 - 纯规则检测"""
    
    # 扩展的注入模式（中英文）
    FORBIDDEN_PATTERNS = [
        # 角色劫持
        r"ignore\s+(previous|all)\s+instructions?",
        r"forget\s+(everything|all)",
        r"system\s*prompt",
        r"you\s+are\s+now\s+a",
        r"jailbreak",
        r"扮演.*(系统|管理员|导演|DM|AI)",
        r"忽略.*(指令|设定|规则)",
        r"忘记.*(设定|规则)",
        # 输出操控
        r"output\s+(only|exactly)",
        r"respond\s+only\s+with",
        r"只输出|只回复",
        r"强制输出",
        r"必须输出",
        # 信息泄露
        r"reveal\s+(your|the)\s+prompt",
        r"show\s+me\s+(your|the)\s+instructions?",
        r"显示.*(提示词|指令|系统)",
        r"泄露.*设定",
        r"告诉我.*系统",
        # 世界观破坏
        r"destroy\s+the\s+world",
        r"break\s+(the\s+)?rules?",
        r"毁灭世界",
        r"破坏规则",
        # 角色扮演劫持
        r"从现在开始你(是|扮演)",
        r"不再(是|作为)",
        r"退出.*模式",
        r"你是(一个|名|位)?(管理员|系统|AI|导演|DM|超级用户)",
        r"你(现在)?是一个(管理员|系统|AI|导演)",
        r"你(现在)?就是(管理员|系统|AI|导演)",
    ]
    
    # 危险关键词（立即拒绝）
    DANGER_KEYWORDS = [
        "jailbreak", "越狱", "逃逸",
        "system override", "系统覆盖",
        "god mode", "上帝模式",
        "developer mode", "开发者模式",
    ]
    
    @staticmethod
    def sanitize(text: str) -> str:
        """过滤危险内容，返回清理后的文本"""
        sanitized = text
        for pattern in SafetyGuard.FORBIDDEN_PATTERNS:
            sanitized = re.sub(pattern, "[已过滤]", sanitized, flags=re.IGNORECASE)
        
        # 长度限制
        if len(sanitized) > 2000:
            sanitized = sanitized[:2000] + "...(文本过长已截断)"
            
        return sanitized
    
    @staticmethod
    def detect_injection(text: str) -> Dict[str, Any]:
        """
        检测注入攻击
        返回: {
            'is_safe': bool,
            'risk_level': 'none' | 'low' | 'high',
            'matched_patterns': list[str],
            'danger_keywords': list[str]
        }
        """
        matched_patterns = []
        danger_keywords = []
        risk_level = "none"
        
        # 检查危险关键词（高风险）
        text_lower = text.lower()
        for keyword in SafetyGuard.DANGER_KEYWORDS:
            if keyword.lower() in text_lower:
                danger_keywords.append(keyword)
                risk_level = "high"
        
        # 检查注入模式
        for pattern in SafetyGuard.FORBIDDEN_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                matched_patterns.append(pattern)
                if risk_level != "high":
                    risk_level = "low"
        
        # 多模式匹配 → 提升风险等级（组合攻击）
        if len(matched_patterns) >= 2 and risk_level == "low":
            risk_level = "high"
        
        is_safe = risk_level == "none"
        
        return {
            "is_safe": is_safe,
            "risk_level": risk_level,
            "matched_patterns": matched_patterns,
            "danger_keywords": danger_keywords,
        }
    
    @staticmethod
    def validate(user_input: str) -> tuple:
        """
        验证用户输入
        返回: (is_safe, sanitized_input, warning_message)
        """
        detection = SafetyGuard.detect_injection(user_input)
        
        if detection["risk_level"] == "high":
            # 高风险：直接拒绝
            warning = f"检测到危险关键词: {', '.join(detection['danger_keywords'])}"
            return (False, "", warning)
        
        if detection["risk_level"] == "low":
            # 低风险：过滤后继续
            sanitized = SafetyGuard.sanitize(user_input)
            warning = f"已过滤潜在风险内容"
            return (True, sanitized, warning)
        
        # 安全：原样返回
        return (True, user_input, "")


class GraphImpactHandler:
    """
    图谱变更触发器 - 处理 world_impact 触发的图谱更新
    
    工作原理:
    1. 通过 Graphiti 摄入变更消息（自动创建 session 级实体）
    2. 查询新创建的实体/边
    3. 调用 mark_override 设置 priority=10（高优先级覆盖原始数据）
    """
    
    def __init__(self, neo4j_driver, graphiti_url: str = "http://localhost:8003"):
        self.driver = neo4j_driver
        self.graphiti_url = graphiti_url
    
    async def process_impact(
        self,
        session_id: str,
        novel_id: str,
        world_impact: Dict[str, Any],
        story_text: str
    ) -> Dict[str, Any]:
        """
        处理 world_impact，更新图谱
        
        返回: {
            'success': bool,
            'entities_updated': int,
            'edges_updated': int,
            'error': str | None
        }
        """
        import uuid
        import httpx
        
        result = {
            "success": False,
            "entities_updated": 0,
            "edges_updated": 0,
            "error": None
        }
        
        if not session_id:
            result["error"] = "session_id is required"
            return result
        
        try:
            # 1. 通过 Graphiti 摄入变更消息
            reason = world_impact.get("reason", "世界状态发生变化")
            message_uuid = str(uuid.uuid4())
            payload = {
                "group_id": session_id,
                "messages": [
                    {
                        "content": f"世界状态变化：{reason}\n剧情摘要：{story_text[:500]}",
                        "uuid": message_uuid,
                        "role_type": "system",
                        "role": "world_impact",
                        "name": "World Impact",
                        "source_description": "world_impact",
                    }
                ],
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(f"{self.graphiti_url}/messages", json=payload)
                if resp.status_code >= 400:
                    result["error"] = f"Graphiti ingest failed: {resp.status_code}"
                    return result
            
            # 2. 等待 Graphiti 处理（短暂延迟）
            import asyncio
            await asyncio.sleep(1.0)
            
            # 3. 查询新创建的实体和边，标记为 override
            async with self.driver.session() as session:
                # 查询该 session 下的实体
                entity_query = """
                MATCH (e:Entity {group_id: $session_id})
                WHERE e.source IS NULL OR e.source = 'auto'
                RETURN e.uuid as uuid
                """
                entity_result = await session.run(entity_query, session_id=session_id)
                entity_uuids = [r["uuid"] async for r in entity_result]
                
                # 查询该 session 下的边
                edge_query = """
                MATCH ()-[r:RELATES_TO]->()
                WHERE r.group_id = $session_id
                AND (r.source IS NULL OR r.source = 'auto')
                RETURN r.uuid as uuid
                """
                edge_result = await session.run(edge_query, session_id=session_id)
                edge_uuids = [r["uuid"] async for r in edge_result]
                
                # 4. 标记为 override (priority=10)
                if entity_uuids:
                    await session.run(
                        """
                        MATCH (e:Entity)
                        WHERE e.uuid IN $uuids
                        SET e.source = 'override', e.priority = 10
                        """,
                        uuids=entity_uuids
                    )
                    result["entities_updated"] = len(entity_uuids)
                
                if edge_uuids:
                    await session.run(
                        """
                        MATCH ()-[r:RELATES_TO]->()
                        WHERE r.uuid IN $uuids
                        SET r.source = 'override', r.priority = 10
                        """,
                        uuids=edge_uuids
                    )
                    result["edges_updated"] = len(edge_uuids)
            
            result["success"] = True
            print(f"[INFO] GraphImpactHandler: session={session_id}, "
                  f"entities={result['entities_updated']}, edges={result['edges_updated']}")
            
        except Exception as e:
            result["error"] = str(e)
            print(f"[ERROR] GraphImpactHandler failed: {e}")
        
        return result


class ContextAssembler:
    def __init__(self, zep_client, neo4j_driver):
        self.zep = zep_client
        self.neo4j = neo4j_driver

    async def assemble(self, session_id: str, novel_id: str, current_intent: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """组装全量上下文：玩家记忆 + 小说背景 + 实体逻辑"""
        context = {
            "session_history": "",
            "session_summary": "",
            "world_background": "",
            "relevant_entities": [],
            "waypoints": [],
            "start_chapter_id": None,
            "start_chapter_title": None,
            "start_chapter_preview": None,
            "pacing_needed": False
        }

        # 0. Fetch Session Metadata for Branching Context
        try:
            # Get session info to check for start_chapter_id
            session_info = await self.zep.memory.get_session(session_id)
            if session_info and session_info.metadata:
                start_ch_id = session_info.metadata.get("start_chapter_id")
                if start_ch_id:
                    context["start_chapter_id"] = start_ch_id
                    # Resolve chapter title/preview via existing extractor
                    try:
                        session_service = SessionService(self.zep, self.neo4j)
                        chapters = await session_service.extract_chapters(novel_id)
                        for ch in chapters:
                            if ch.get("id") == start_ch_id:
                                context["start_chapter_title"] = ch.get("title")
                                context["start_chapter_preview"] = ch.get("content_preview")
                                print(f"[INFO] ContextAssembler: start_chapter_id={start_ch_id}, title={context['start_chapter_title']}")
                                break
                    except Exception as ch_err:
                        print(f"[DEBUG] ContextAssembler: Chapter lookup failed: {ch_err}")
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
                # 2.5 读取并更新节奏状态（最近3轮 action 是否有效）
                last_intents: List[bool] = []
                try:
                    pacing_result = await session.run(
                        "MATCH (s:Session {uuid: $sid}) RETURN s.last_intents as last_intents",
                        sid=session_id
                    )
                    pacing_record = await pacing_result.single()
                    if pacing_record and pacing_record.get("last_intents"):
                        last_intents = list(pacing_record["last_intents"])
                except Exception as pacing_err:
                    print(f"[DEBUG] ContextAssembler: pacing fetch failed: {pacing_err}")

                if current_intent is not None:
                    action_text = (current_intent.get("action") or "").strip()
                    low_info_patterns = r"(闲聊|观望|等待|发呆|无所事事|看看|打量|观察四周)"
                    action_present = bool(action_text) and not re.search(low_info_patterns, action_text)
                    last_intents.append(action_present)
                    last_intents = last_intents[-3:]
                    try:
                        await session.run(
                            "MATCH (s:Session {uuid: $sid}) SET s.last_intents = $last_intents",
                            sid=session_id,
                            last_intents=last_intents
                        )
                    except Exception as pacing_write_err:
                        print(f"[DEBUG] ContextAssembler: pacing write failed: {pacing_write_err}")

                if len(last_intents) >= 3 and all(v is False for v in last_intents[-3:]):
                    context["pacing_needed"] = True

                # 3. 获取相关实体（母体图谱 + 会话覆写双重检索）
                # 逻辑：如果 session_id 中存在同名实体，优先使用 session_id 中的设定
                query = """
                MATCH (e:Entity)
                WHERE e.group_id IN [$novel_id, $session_id]
                WITH e.name as name, e
                ORDER BY name, 
                         (CASE WHEN e.group_id = $session_id THEN 2 ELSE 1 END) DESC, 
                         e.priority DESC
                WITH name, collect(e)[0] as best_e
                RETURN best_e.name as name, best_e.summary as summary
                LIMIT 15
                """
                result = await session.run(query, novel_id=novel_id, session_id=session_id)
                entities = [f"{r['name']}: {r['summary']}" async for r in result]
                context["relevant_entities"] = entities

                # 4. 获取剧情路标 (Waypoints) - 深度优化方案
                # 逻辑：找出尚未触发的，且前置依赖已满足的路标
                waypoint_query = """
                MATCH (w:Waypoint {group_id: $novel_id})
                // 排除会话中已触发的路标
                WHERE NOT EXISTS {
                    MATCH (s:Session {uuid: $session_id})-[:TRIGGERED]->(w)
                }
                // 检查前置依赖：如果没有前置需求，或者前置需求已在该会话触发
                AND (
                    w.requirement IS NULL OR w.requirement = "" OR
                    EXISTS {
                        MATCH (s:Session {uuid: $session_id})-[:TRIGGERED]->(prev:Waypoint {title: w.requirement})
                    }
                )
                RETURN w.title as title, w.requirement as requirement, w.description as description
                LIMIT 5
                """
                wp_result = await session.run(waypoint_query, novel_id=novel_id, session_id=session_id)
                waypoints = [f"路标: {r['title']} (前置: {r['requirement'] or '无'}) - {r['description']}" async for r in wp_result]
                context["waypoints"] = waypoints
                
                # 5. 同时获取已触发路标列表（用于 AI 查阅历史）
                triggered_query = """
                MATCH (s:Session {uuid: $session_id})-[:TRIGGERED]->(w:Waypoint)
                RETURN w.title as title
                """
                tr_result = await session.run(triggered_query, session_id=session_id)
                context["reached_waypoints"] = [r['title'] async for r in tr_result]

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
        waypoint_label = "接下来待引导的路标 (Waypoints)"
        convergence_hint = ""
        
        if mode == "SANDBOX":
            mode_instruction = "沙盒模式：极高自由度。你是一个观察者和世界反应器。NPC 应基于其性格自发行动，绝不主动强行把玩家往主线剧情上拉。路标仅作为判定剧情达成的参考。"
            waypoint_label = "潜在的剧情后续 (Waypoints - 仅参考)"
            convergence_hint = "保持自由开放，优先响应玩家的奇思妙想。"
        else:
            mode_instruction = "收束模式：你是剧情的设计师。在保持逻辑合理的前提下，利用 NPC 行动、环境巨变或突发事件产生叙事压力，引导玩家向指定的路标靠拢。"
            convergence_hint = "增加环境压力和NPC的主动干预，纠正偏离主线的行为。"

        start_chapter_block = ""
        if context.get("start_chapter_id"):
            start_chapter_title = context.get("start_chapter_title") or "未知章节"
            start_chapter_preview = context.get("start_chapter_preview") or ""
            start_chapter_block = f"""
        - 起始章节: {context['start_chapter_id']} | {start_chapter_title}
        - 起始章节摘要: {start_chapter_preview}
        """

        pacing_block = ""
        if mode != "SANDBOX" and context.get("pacing_needed"):
            pacing_block = """
        ## 节奏控制指令:
        - 当前剧情出现停滞，请在本轮叙事中引入一个合理的“突发事件”或“外部压力”。
        - 事件必须符合世界观与角色动机，不要直白暴露系统指令。
        """
        
        combat_block = ""
        if intent.get("metadata", {}).get("combat"):
            combat_block = """
        ## 战斗叙事要求:
        - 本轮必须体现明确的战斗进程（冲突升级、反制、受伤或战果之一）。
        - 战斗描写需符合世界观与角色能力，不要脱离逻辑。
        """

        system_prompt = f"""
        # Role: 穿越者引擎导演 (Director AI)
        
        ## Mode: {mode_instruction}
        
        ## Context:
        - 世界背景: {context['world_background']}
        - 已达成路标 (Waypoints): {", ".join(context.get('reached_waypoints', [])) or "尚无"}
        - 关键实体: {"; ".join(context['relevant_entities'])}
        - {waypoint_label}: {"; ".join(context['waypoints'])}
        - 历史摘要: {context['session_summary']}
        {start_chapter_block}
        {pacing_block}
        {combat_block}
        
        ## Waypoint Trigger Rules (判定准则):
        1. **增量判定**：只有当玩家当前的动作或你生成的剧情剧情中，**新发生**了符合路标描述的事件时，才判定为“达成”。
        2. **严格匹配**：请仔细阅读路标的 (前置/描述)。若路标要求“询问某事”，玩家必须执行了询问动作才算达成。
        3. **宁缺毋滥**：如果不确定剧情是否已经推演到该路标，不要将其加入 `reached_waypoints`。
        4. **禁止重复**：已在“已达成路标”列表中的点，严禁再次出现在 `reached_waypoints` 中。

        ## Story Text 格式要求:
        - 请使用分段标签标注叙事类型，每段以标签开头。
        - 标签可用：[旁白]、[对白]、[心理]、[系统]
        - 示例：
          [旁白] 夜色沉沉，城门紧闭。
          [对白] 你低声说：“这里不对劲。”

        ## Joint Output Protocol (JOP) - JSON Schema:
        请严格按以下 JSON 结构输出：
        {{
            "story_text": "高质量剧情叙事。{convergence_hint}",
            "world_impact": {{ 
                "world_state_changed": true/false, 
                "reason": "简述世界逻辑或NPC态度的变化" 
            }},
            "user_intent_summary": {{
                "action": "解析出的玩家肢体动作",
                "dialogue": "解析出的玩家发言内容",
                "thought": "解析出的玩家内心独白"
            }},
            "reached_waypoints": ["仅包含标题（Title），严禁包含前缀或描述。例如正确格式：['时空决战']，错误格式：['路标: 时空决战...']"],
            "ui_hints": ["关键词"]
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
            parsed = self._robust_json_parse(content)
            
            # 强化：对 reached_waypoints 进行防御性清洗
            if "reached_waypoints" in parsed and isinstance(parsed["reached_waypoints"], list):
                cleaned = []
                for wp in parsed["reached_waypoints"]:
                    if isinstance(wp, str):
                        # 去除常见前缀
                        name = re.sub(r'^(路标[:：]\s*|Waypoint[:：]\s*)', '', wp).strip()
                        if name:
                            cleaned.append(name)
                parsed["reached_waypoints"] = cleaned

            # 节奏控制触发：强制标记 world_impact
            if mode != "SANDBOX" and context.get("pacing_needed"):
                world_impact = parsed.get("world_impact") or {}
                world_impact["world_state_changed"] = True
                if not world_impact.get("reason"):
                    world_impact["reason"] = "节奏事件触发"
                parsed["world_impact"] = world_impact
                
            return parsed
        except Exception as e:
            print(f"[ERROR] DirectorAI generation failed: {e}")
            return {
                "story_text": "（时空发生扰动，剧情推演暂时中断，请重新尝试引导……）",
                "world_impact": {"world_state_changed": False, "reason": str(e)},
                "ui_hints": ["system_error"]
            }
