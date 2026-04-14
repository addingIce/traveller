import asyncio
import logging
import os
import re
import time
import json
from typing import Annotated, Any
from contextvars import ContextVar

from fastapi import Depends, HTTPException
from graphiti_core import Graphiti  # type: ignore
from graphiti_core.edges import EntityEdge  # type: ignore
from graphiti_core.errors import EdgeNotFoundError, GroupsEdgesNotFoundError, NodeNotFoundError
from graphiti_core.llm_client import LLMClient  # type: ignore
from graphiti_core.nodes import EntityNode, EpisodicNode  # type: ignore

from graph_service.config import ZepEnvDep
from graph_service.dto import FactResult

logger = logging.getLogger(__name__)
import neo4j
os.environ["NO_PROXY"] = "*"
os.environ["http_proxy"] = ""
os.environ["https_proxy"] = ""

def _ensure_vectors(query, params):
    """确保必要的字段存在，不再注入 Mock 向量（使用真实 Embedding）"""
    if not isinstance(params, dict): return
    
    # Check for nodes list (bulk save)
    if 'nodes' in params and isinstance(params['nodes'], list):
        for node in params['nodes']:
            if isinstance(node, dict):
                if node.get('source') is None:
                    node['source'] = 'auto'
                if node.get('priority') is None:
                    node['priority'] = 0
    
    # Check for entity_data (single save)
    if 'entity_data' in params and isinstance(params['entity_data'], dict):
        if params['entity_data'].get('source') is None:
            params['entity_data']['source'] = 'auto'
        if params['entity_data'].get('priority') is None:
            params['entity_data']['priority'] = 0
            
    # Check for edges list (bulk edges)
    if 'entity_edges' in params and isinstance(params['entity_edges'], list):
        for edge in params['entity_edges']:
            if isinstance(edge, dict):
                if edge.get('source') is None:
                    edge['source'] = 'auto'
                if edge.get('priority') is None:
                    edge['priority'] = 0

    # Direct check for source/priority
    if 'source' in params and params['source'] is None:
        params['source'] = 'auto'
    if 'priority' in params and params['priority'] is None:
        params['priority'] = 0

_original_run = neo4j.AsyncSession.run
async def _hooked_run(self, *args, **kwargs):
    query = args[0] if args else kwargs.get('query', '')
    params = kwargs.get('parameters') or (args[1] if len(args) > 1 else {})
    _ensure_vectors(query, params)
    return await _original_run(self, *args, **kwargs)
neo4j.AsyncSession.run = _hooked_run

from neo4j._async.work.transaction import AsyncManagedTransaction
_original_tx_run = AsyncManagedTransaction.run
async def _hooked_tx_run(self, *args, **kwargs):
    query = args[0] if args else kwargs.get('query', '')
    # Graphiti calls tx.run(query, parameters, **kwargs)
    params = {}
    if len(args) > 1 and isinstance(args[1], dict):
        params.update(args[1])
    params.update(kwargs.get('parameters', {}))
    # Mixin top level kwargs that might be params
    params.update({k: v for k, v in kwargs.items() if k not in ['query', 'parameters']})
    
    _ensure_vectors(query, params)
    return await _original_tx_run(self, *args, **kwargs)
AsyncManagedTransaction.run = _hooked_tx_run
# Hook everything in multiple namespaces
import graphiti_core.graphiti as g_core
import graphiti_core.utils.bulk_utils as bulk_mod
import graphiti_core.utils.maintenance.node_operations as node_ops
import sys

_original_bulk = bulk_mod.add_nodes_and_edges_bulk
async def _hooked_bulk(driver, episodic_nodes, episodic_edges, entity_nodes, entity_edges, embedder):
    msg = f"!!! [PRINT] BULK SAVE CALL !!! Entities: {len(entity_nodes)}, Edges: {len(entity_edges)}, Episodic: {len(episodic_nodes)}"
    print(msg, flush=True)
    
    # 清理实体节点中的非原始类型字段（Neo4j 不支持嵌套 Map）
    # 这些字段是 graphiti 内部用于去重和矛盾检测的，不应存入 Neo4j
    fields_to_remove = ['duplicate_fact_idx', 'contradicted_facts']
    for node in entity_nodes:
        for field in fields_to_remove:
            if hasattr(node, field):
                delattr(node, field)
            elif isinstance(node, dict) and field in node:
                del node[field]
    
    # 同样清理边（edges）
    for edge in entity_edges:
        for field in fields_to_remove:
            if hasattr(edge, field):
                delattr(edge, field)
            elif isinstance(edge, dict) and field in edge:
                del edge[field]
    
    # 不再注入 Mock 向量，使用真实 Embedding
    return await _original_bulk(driver, episodic_nodes, episodic_edges, entity_nodes, entity_edges, embedder)

# Brute force patch
for mod in [g_core, bulk_mod, sys.modules.get('graphiti_core.graphiti')]:
    if mod and hasattr(mod, 'add_nodes_and_edges_bulk'):
        mod.add_nodes_and_edges_bulk = _hooked_bulk

_original_resolve = node_ops.resolve_extracted_nodes
async def _hooked_resolve(*args, **kwargs):
    print("!!! [PRINT] RESOLVE NODES START !!!", flush=True)
    res = await _original_resolve(*args, **kwargs)
    nodes, _, _ = res
    print(f"!!! [PRINT] RESOLVE NODES END RESULT !!! Count: {len(nodes)}", flush=True)
    return res
node_ops.resolve_extracted_nodes = _hooked_resolve
if hasattr(g_core, 'resolve_extracted_nodes'):
    g_core.resolve_extracted_nodes = _hooked_resolve

_original_attributes = node_ops.extract_attributes_from_nodes
async def _hooked_attributes(*args, **kwargs):
    print("!!! [PRINT] ATTRIBUTES EXTRACTION START !!!", flush=True)
    # 优化：不传 previous_episodes（原始文本），只依赖实体历史摘要和属性
    # 这样可以大幅减少 LLM 请求长度（从 ~72k 字符降到 ~7k 字符）
    if 'previous_episodes' in kwargs:
        kwargs['previous_episodes'] = []
    elif len(args) > 3:
        args = list(args)
        args[3] = []
        args = tuple(args)
    res = await _original_attributes(*args, **kwargs)
    print(f"!!! [PRINT] ATTRIBUTES EXTRACTION END RESULT !!! Count: {len(res)}", flush=True)
    return res
node_ops.extract_attributes_from_nodes = _hooked_attributes
if hasattr(g_core, 'extract_attributes_from_nodes'):
    g_core.extract_attributes_from_nodes = _hooked_attributes

# Fix TypeError: duplicate_fact_id 类型错误
import graphiti_core.utils.maintenance.edge_operations as edge_ops
_original_resolve_edge = edge_ops.resolve_extracted_edge
async def _hooked_resolve_edge(*args, **kwargs):
    """
    包装 resolve_extracted_edge 函数，修复 duplicate_fact_id 类型问题。
    确保 duplicate_fact_id 始终是整数而不是列表。
    """
    try:
        result = await _original_resolve_edge(*args, **kwargs)
        # result 是一个元组 (duplicate_fact_id, fact_type, contradicted_facts)
        if isinstance(result, tuple) and len(result) > 0:
            duplicate_fact_id = result[0]
            # 如果 duplicate_fact_id 是列表，取第一个元素
            if isinstance(duplicate_fact_id, list):
                logger.warning(f"duplicate_fact_id is a list: {duplicate_fact_id}, extracting first element")
                new_duplicate_fact_id = duplicate_fact_id[0] if duplicate_fact_id else -1
                # 返回修复后的元组
                return (new_duplicate_fact_id,) + result[1:]
        return result
    except TypeError as e:
        # 如果仍然出现类型错误，尝试修复
        if "'<=' not supported between instances of 'int' and 'list'" in str(e):
            logger.error(f"TypeError in resolve_extracted_edge: {e}")
            # 返回默认值避免崩溃
            return (-1, "DEFAULT", [])
        raise
edge_ops.resolve_extracted_edge = _hooked_resolve_edge
if hasattr(g_core, 'resolve_extracted_edge'):
    g_core.resolve_extracted_edge = _hooked_resolve_edge

_original_execute = neo4j.AsyncDriver.execute_query
async def _hooked_execute(self, query_, *args, **kwargs):
    params = kwargs.get('parameters_') or kwargs.get('params') or kwargs.get('parameters') or (args[0] if args else {})
    _ensure_vectors(str(query_), params)
    try:
        return await _original_execute(self, query_, *args, **kwargs)
    except Exception as e:
        query_text = str(query_ or "")
        error_text = str(e)
        if (
            "TooManyClauses" in error_text
            and (
                "db.index.fulltext.queryRelationships" in query_text
                or "db.index.fulltext.queryNodes" in query_text
            )
        ):
            logger.warning(
                "Neo4j fulltext query hit TooManyClauses; falling back to empty result. query=%s",
                query_text.splitlines()[0][:120],
            )
            # 与 neo4j AsyncDriver.execute_query 返回结构保持一致: (records, summary, keys)
            return [], None, []
        raise
neo4j.AsyncDriver.execute_query = _hooked_execute


_LLM_MAX_CONCURRENCY = int(os.getenv("GRAPHITI_LLM_MAX_CONCURRENCY", "1"))
_LLM_MIN_INTERVAL = float(os.getenv("GRAPHITI_LLM_MIN_INTERVAL", "0.0"))
_llm_semaphore = asyncio.Semaphore(_LLM_MAX_CONCURRENCY)
_last_llm_call: float = 0.0 # GLOBAL

def _utc_now_monotonic() -> float:
    return asyncio.get_running_loop().time()


class ZepGraphiti(Graphiti):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def mark_override(self, node_uuids: list[str], edge_uuids: list[str]) -> None:
        if node_uuids:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MATCH (n:Entity)
                    WHERE n.uuid IN $uuids
                    SET n.source = 'override', n.priority = 10
                    """,
                    uuids=node_uuids,
                )
        if edge_uuids:
            async with self.driver.session() as session:
                await session.run(
                    """
                    MATCH ()-[r:RELATES_TO]->()
                    WHERE r.uuid IN $uuids
                    SET r.source = 'override', r.priority = 10
                    """,
                    uuids=edge_uuids,
                )

    async def save_entity_node(self, name: str, uuid: str, group_id: str, summary: str = ''):
        new_node = EntityNode(
            name=name,
            uuid=uuid,
            group_id=group_id,
            summary=summary,
        )
        await new_node.generate_name_embedding(self.embedder)
        await new_node.save(self.driver)
        return new_node

    async def add_episode(self, *args, **kwargs):
        uuid_val = kwargs.get('uuid')
        logger.error(f"ZepGraphiti.add_episode START. UUID: {uuid_val}")
        try:
            uuid_val = kwargs.get('uuid') # Corrected from `uuid_val = uuid_`
            print(f"!!! [PRINT] CALLING SUPER.add_episode for {uuid_val}", flush=True)
            res = await super().add_episode(*args, **kwargs)
            source_description = kwargs.get('source_description') or getattr(res.episode, 'source_description', '')
            if isinstance(source_description, str) and "world_impact" in source_description:
                node_uuids = [n.uuid for n in res.nodes if getattr(n, "uuid", None)]
                edge_uuids = [e.uuid for e in res.edges if getattr(e, "uuid", None)]
                await self.mark_override(node_uuids, edge_uuids)
            print(f"!!! [PRINT] SUPER.add_episode SUCCESS for {uuid_val}", flush=True)
            return res
        except Exception as e:
            logger.error(f"ZepGraphiti.add_episode FAILED. UUID: {uuid_val}, Error: {str(e)}")
            import traceback # Moved inside except block and corrected typo
            logger.error(traceback.format_exc())
            raise

    async def get_entity_edge(self, uuid: str):
        try:
            edge = await EntityEdge.get_by_uuid(self.driver, uuid)
            return edge
        except EdgeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e

    async def delete_group(self, group_id: str):
        try:
            edges = await EntityEdge.get_by_group_ids(self.driver, [group_id])
        except GroupsEdgesNotFoundError:
            logger.warning(f'No edges found for group {group_id}')
            edges = []

        nodes = await EntityNode.get_by_group_ids(self.driver, [group_id])

        episodes = await EpisodicNode.get_by_group_ids(self.driver, [group_id])

        for edge in edges:
            await edge.delete(self.driver)

        for node in nodes:
            await node.delete(self.driver)

        for episode in episodes:
            await episode.delete(self.driver)

    async def delete_entity_edge(self, uuid: str):
        try:
            edge = await EntityEdge.get_by_uuid(self.driver, uuid)
            await edge.delete(self.driver)
        except EdgeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e

    async def delete_episodic_node(self, uuid: str):
        try:
            episode = await EpisodicNode.get_by_uuid(self.driver, uuid)
            await episode.delete(self.driver)
        except NodeNotFoundError as e:
            raise HTTPException(status_code=404, detail=e.message) from e


from graphiti_core.llm_client import OpenAIClient, LLMConfig
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from pydantic import BaseModel

_current_response_model: ContextVar[type[BaseModel] | None] = ContextVar("_current_response_model", default=None)

_MAP_FIELDS_TO_STRINGIFY = {"attributes", "properties", "metadata"}

def _sanitize_payload(data: Any) -> Any:
    if isinstance(data, dict):
        new_dict: dict[str, Any] = {}
        for k, v in data.items():
            if k in _MAP_FIELDS_TO_STRINGIFY:
                if isinstance(v, (dict, list)):
                    # ensure_ascii=False 保留中文字符，避免转义为 Unicode 编码
                    new_dict[k] = json.dumps(v, ensure_ascii=False)
                else:
                    new_dict[k] = v
            else:
                new_dict[k] = _sanitize_payload(v)
        return new_dict
    if isinstance(data, list):
        return [_sanitize_payload(item) for item in data]
    return data

class ResilientOpenAIClient(OpenAIClient):
    """
    一个更健壮的 OpenAI 客户端，处理那些不完全遵循 structural output 的模型。
    它会手动清理结果中的 markdown 标签并尝试解析 JSON。
    """
    async def _generate_response(self, *args, **kwargs):
        global _last_llm_call
        messages = kwargs.get('messages') or (args[0] if args else [])
        response_model = kwargs.get('response_model') or (args[1] if len(args) > 1 else None)
        msg_count = len(messages)
        max_tokens = kwargs.get('max_tokens', 8192)
        
        # 计算消息总长度用于诊断
        total_chars = sum(len(getattr(m, 'content', '') or '') for m in messages) if messages else 0
        print(f"!!! [PRINT] LLM REQUEST START - Model: {response_model.__name__ if response_model else 'None'} - Msg count: {msg_count} - Total chars: {total_chars}", flush=True)
        if total_chars == 0:
            logger.error("LLM REQUEST has EMPTY content! Messages will be logged.")
            for i, m in enumerate(messages or []):
                logger.error(f"Message {i}: {repr(m)[:500]}")

        token = _current_response_model.set(response_model)
        max_retries = 5
        try:
            for attempt in range(max_retries):
                try:
                    async with _llm_semaphore:
                        if _LLM_MIN_INTERVAL > 0:
                            now = time.time()
                            wait_time = _LLM_MIN_INTERVAL - (now - _last_llm_call)
                            if wait_time > 0:
                                await asyncio.sleep(wait_time)
                            _last_llm_call = time.time()

                        # 注入 ID 规则与语言规则提醒
                        if messages and len(messages) > 0:
                            # Message 对象是 Pydantic 模型，使用属性访问
                            last_msg_obj = messages[-1]
                            last_msg = getattr(last_msg_obj, 'content', '') or ""
                            # 增加语言一致性规则：强制使用原文语言（中文）
                            lang_rule = (
                                "\n\nLANGUAGE RULE: All output (names, relationship facts, descriptions) must use the SAME LANGUAGE as the input text. "
                                "If the input is Chinese, your output must be Chinese. Do not use English relationship names like 'LIKES' or 'WORKS_AT' if the story is in Chinese."
                            )
                            # ID 规则
                            id_rule = "\n\nCRITICAL ID RULE: Use the exact 'id' or 'entity_id' from the provided ENTITIES list. Do not use 1-based indexing if the list uses 0-based. Your project IDs must match the input IDs exactly."
                            # entity_type_id 规则：修复 ValidationError + 统一类型映射
                            entity_type_rule = (
                                "\n\nIMPORTANT FIELD RULE: Every entity object MUST include 'entity_type_id' field. "
                                "Use ONLY the following mapping: 1=人物, 2=地点, 3=组织, 4=物品, 5=概念, 0=未知. "
                                "Never omit this field."
                            )
                            # duplicate_fact_idx 规则：修复 TypeError
                            duplicate_rule = "\n\nIMPORTANT FIELD RULE: The 'duplicate_fact_idx' field must ALWAYS be an integer (-1 if no duplicate). Never return a list for this field. Similarly, 'contradicted_facts' should be a list of integers, not nested lists."
                            # 排除规则：不提取通用角色名（注意：消息中的 role:user 是 API 格式，不是故事角色）
                            exclusion_rule = "\n\nCRITICAL EXCLUSION RULE: Do NOT extract 'user', '讲述者', 'narrator', 'speaker', 'assistant' as entities. These are API message roles (like role:user), NOT characters in the story. Ignore them completely."
                            
                            # 严格实体提取规则：只提取有名字的重要实体
                            strict_entity_rule = """
\n\nSTRICT ENTITY EXTRACTION RULES:
- ONLY extract entities with PROPER NAMES (e.g., "唐三", "小舞", "史莱克学院", "佛怒唐莲")
- DO NOT extract generic references: "少年", "老者", "那人", "少女", "男子", "女子", "孩子", "老人"
- DO NOT extract generic locations: "一个房间", "那座山", "这里", "那里"
- DO NOT extract generic items: "一把剑", "那件衣服", "这个东西"
- DO NOT extract abstract concepts without names
- ONLY extract characters that appear multiple times or have significant roles
- When in doubt about an entity's importance, DO NOT extract it
- Quality over quantity: 5 important entities are better than 20 minor ones"""

                            # 严格关系提取规则：只提取推动剧情的关键关系
                            strict_relationship_rule = """
\n\nSTRICT RELATIONSHIP EXTRACTION RULES:
- ONLY extract relationships that are significant to the plot or character development.
- DO NOT extract trivial or obvious relationships (e.g., "A stood next to B", "A saw B").
- AVOID redundant relationships. If a relationship is already implied or stated, do not extract it again.
- Preferred relations: Family (father/son), Sect/Organization (disciple/master), Emotions (love/hate), Plot-driven (enemies/allies).
- BE CONCISE in fact descriptions. Use "A is B's teacher" instead of "A spent many years teaching B the way of the sword".
- CRITICAL: relation_type MUST be a short Chinese phrase (2-8 Chinese chars), e.g. "要求完成", "帮助修复", "表示赞赏".
- NEVER use pinyin, ALL_CAPS tokens, or underscore style such as "YAQIU_WANCHENG_JINJI_XIANGMU"."""

                            combined_rules = lang_rule + id_rule + entity_type_rule + duplicate_rule + exclusion_rule + strict_entity_rule + strict_relationship_rule
                            
                            if hasattr(last_msg_obj, 'content'):
                                last_msg_obj.content = last_msg + combined_rules
                            else:
                                messages[-1]['content'] = last_msg + combined_rules

                        response = await self._create_completion(
                            self.config.model,
                            messages,
                            temperature=None,
                            max_tokens=max_tokens,
                            response_model=None,
                        )
                        if not hasattr(response, 'choices') or not response.choices:
                            raise Exception(f"Unexpected response format (no choices): {response}")
                        content = response.choices[0].message.content or "{}"
                        logger.error(f"RAW LLM RESPONSE (_generate_response): {repr(content)}")
                        clean_content = self.clean_json_text(content)
                        data = self.safe_parse_json(clean_content)
                        data = self.normalize_data(data)
                        data = self._normalize_indices(data)
                        
                        response_model_inner = _current_response_model.get()
                        if isinstance(data, list):
                            if response_model_inner:
                                fields = list(response_model_inner.model_fields.keys())
                                if fields:
                                    field_name = fields[0]
                                    # 在包装前，如果模型是 ExtractedEntities，给里面的 dict 瘦身并强制 conversion
                                    # 保留 entity_id，因为下游 resolve_nodes 需要它进行排序和映射
                                    if response_model_inner.__name__ == 'ExtractedEntities':
                                        schema_fields = {'name', 'entity_type_id', 'entity_id'}
                                        new_items = []
                                        for item in data:
                                            if not isinstance(item, dict):
                                                new_items.append(item)
                                                continue
                                            cleaned = {k: v for k, v in item.items() if k in schema_fields}
                                            # Pydantic ExtractedEntity 要求 name 必填；缺失则直接丢弃，避免整体失败
                                            if not str(cleaned.get('name') or '').strip():
                                                logger.warning(f"Dropping invalid extracted entity without name: {item}")
                                                continue
                                            # 强制 entity_id 为 int
                                            if 'entity_id' in cleaned:
                                                try: cleaned['entity_id'] = int(cleaned['entity_id'])
                                                except (ValueError, TypeError): cleaned['entity_id'] = 0
                                            new_items.append(cleaned)
                                        data = new_items
                                    
                                    data = {field_name: data}
                                    logger.error(f"Wrapped list response into dict with key '{field_name}'")
                        elif isinstance(data, dict) and response_model_inner:
                            # 检查是否已经是包装好的 dict (e.g., {"edges": [...]})
                            fields = list(response_model_inner.model_fields.keys())
                            if fields and fields[0] in data:
                                inner_key = fields[0]
                                if isinstance(data[inner_key], list):
                                    # 同样进行瘦身与转换
                                    if response_model_inner.__name__ == 'ExtractedEntities':
                                        schema_fields = {'name', 'entity_type_id', 'entity_id'}
                                        new_items = []
                                        for item in data[inner_key]:
                                            if not isinstance(item, dict):
                                                new_items.append(item)
                                                continue
                                            cleaned = {k: v for k, v in item.items() if k in schema_fields}
                                            if not str(cleaned.get('name') or '').strip():
                                                logger.warning(f"Dropping invalid extracted entity without name: {item}")
                                                continue
                                            if 'entity_id' in cleaned:
                                                try: cleaned['entity_id'] = int(cleaned['entity_id'])
                                                except (ValueError, TypeError): cleaned['entity_id'] = 0
                                            new_items.append(cleaned)
                                        data[inner_key] = new_items

                                    data[inner_key] = self.normalize_data(data[inner_key])
                                    data[inner_key] = self._normalize_indices(data[inner_key])
                        
                        logger.error(f"FINAL NORMALIZED DATA (Model: {response_model_inner.__name__ if response_model_inner else 'None'}): {repr(data)}")
                        data = _sanitize_payload(data)
                        _last_llm_call = time.time()
                        return data
                except Exception as e:
                    if attempt < max_retries - 1:
                        wait_sec = 3 * (attempt + 1)
                        logger.error(f"Attempt {attempt+1}/{max_retries} FAILED: {str(e)}. Retrying in {wait_sec} seconds...")
                        await asyncio.sleep(wait_sec)
                        continue
                    else:
                        raise e
            return {}

                # --- 结构化输出路径已移除，统一走通用 completion 并手动解析 ---
        finally:
            _current_response_model.reset(token)

    async def _create_structured_completion(
        self,
        model: str,
        messages: list[Any],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel],
    ):
        # 当前网关对 structured output 兼容性不稳定，先强制走普通 completion。
        # 保留结构化输出路径以便未来恢复。
        return await self._create_completion(model, messages, temperature, max_tokens, response_model=None)

    async def _create_completion(
        self,
        model: str,
        messages: list[Any],
        temperature: float | None,
        max_tokens: int,
        response_model: type[BaseModel] | None,
    ):
        extra_body = {"enable_thinking": False}
        response_format = {"type": "json_object"} if response_model else None
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            extra_body=extra_body,
        )

    def _handle_structured_response(self, response: Any) -> dict[str, Any]:
        # structured output 暂不启用；这里先复用 JSON 清洗逻辑，后续可恢复结构化解析。
        data = self._handle_json_response(response)
        response_model = _current_response_model.get()
        data = self.normalize_data(data)
        if isinstance(data, list) and response_model:
            fields = list(response_model.model_fields.keys())
            if fields:
                logger.error(f"Auto-wrapping list response into field: {fields[0]}")
                return {fields[0]: data}
        return data

    def normalize_data(self, data: Any) -> Any:
        # 递归归一化字典中的键
        if isinstance(data, list):
            return [self.normalize_data(item) for item in data]
        if isinstance(data, dict):
            new_dict = {}
            for k, v in data.items():
                # 归一化键名
                new_key = k
                # 常见的模型偏差字段名映射
                mapping = {
                    # 字段名映射（叶节点）
                    'entity': 'name',
                    'entity_text': 'name',
                    'node': 'name',
                    'entity_name': 'name',
                    'node_name': 'name',
                    'fact_content': 'fact',
                    'fact_text': 'fact',
                    'relationship': 'fact',
                    'relation': 'fact',
                    'description': 'fact',
                    'source_node': 'source_node_uuid',
                    'target_node': 'target_node_uuid',
                    'subject_id': 'source_entity_id',
                    'object_id': 'target_entity_id',
                    'source_id': 'source_entity_id',
                    'target_id': 'target_entity_id',
                    'source_node_id': 'source_entity_id',
                    'target_node_id': 'target_entity_id',
                    'source_entity': 'source_entity_id',
                    'target_entity': 'target_entity_id',
                    'subject_entity_id': 'source_entity_id',
                    'object_entity_id': 'target_entity_id',
                    # 关系抽取常见嵌套写法（subject/object）映射
                    # 后续会在 id_field 归一化阶段把 dict 提取为整数 id
                    'subject': 'source_entity_id',
                    'object': 'target_entity_id',
                    # 顶层 key 映射（DeepSeek 常用 vs Graphiti 期望）
                    'entities': 'extracted_entities',
                    'edges': 'edges',
                    'relations': 'edges',
                    'relationships': 'edges',
                    'facts': 'edges',
                    'extracted_facts': 'edges',
                    'resolutions': 'entity_resolutions',
                }
                if k in mapping:
                    new_key = mapping[k]
                
                new_dict[new_key] = self.normalize_data(v)
            
            # 修复 ValidationError: entity_type_id 缺失
            # 如果检测到实体对象但缺少 entity_type_id，自动添加默认值 0
            if 'entity_id' in new_dict or 'name' in new_dict:
                # 某些模型会返回 text 字段表示实体名，兜底映射为 name
                if ('name' not in new_dict or not str(new_dict.get('name') or '').strip()) and 'text' in new_dict:
                    fallback_name = str(new_dict.get('text') or '').strip()
                    if fallback_name:
                        new_dict['name'] = fallback_name
                if 'entity_type_id' not in new_dict:
                    logger.warning(f"Adding missing entity_type_id to entity: {new_dict.get('name', 'unknown')}")
                    new_dict['entity_type_id'] = 0
                else:
                    try:
                        entity_type_id = int(new_dict['entity_type_id'])
                    except (TypeError, ValueError):
                        entity_type_id = 0
                    if entity_type_id < 0 or entity_type_id > 5:
                        logger.warning(
                            f"Out-of-range entity_type_id ({new_dict['entity_type_id']}) for entity: "
                            f"{new_dict.get('name', 'unknown')} - resetting to 0"
                        )
                        entity_type_id = 0
                    new_dict['entity_type_id'] = entity_type_id
            
            # 修复 TypeError: duplicate_fact_id 类型错误
            # 如果 duplicate_fact_id 是列表，转换为整数
            if 'duplicate_fact_id' in new_dict:
                if isinstance(new_dict['duplicate_fact_id'], list):
                    logger.warning(f"Converting duplicate_fact_id from list to int: {new_dict['duplicate_fact_id']}")
                    new_dict['duplicate_fact_id'] = new_dict['duplicate_fact_id'][0] if new_dict['duplicate_fact_id'] else -1
            
            # 修复 contradicted_facts 类型错误
            # 确保 contradicted_facts 是整数列表，不是嵌套列表
            if 'contradicted_facts' in new_dict:
                if isinstance(new_dict['contradicted_facts'], list):
                    # 展平嵌套列表
                    flattened = []
                    for item in new_dict['contradicted_facts']:
                        if isinstance(item, list):
                            flattened.extend(item)
                        else:
                            flattened.append(item)
                    new_dict['contradicted_facts'] = flattened
            
            # 修复 source_entity_id 和 target_entity_id 类型错误
            # LLM 有时会返回 {"id": 0, "name": "xxx"} 而不是整数
            for id_field in ['source_entity_id', 'target_entity_id', 'source_id', 'target_id']:
                if id_field in new_dict:
                    val = new_dict[id_field]
                    if isinstance(val, dict):
                        # 从 dict 中提取 id 字段
                        extracted_id = val.get('id', val.get('entity_id', 0))
                        logger.warning(f"Converting {id_field} from dict to int: {val} -> {extracted_id}")
                        new_dict[id_field] = extracted_id
                    elif not isinstance(val, int):
                        # 尝试转换为整数
                        try:
                            new_dict[id_field] = int(val)
                        except (TypeError, ValueError):
                            logger.warning(f"Invalid {id_field} value: {val}, setting to 0")
                            new_dict[id_field] = 0

            # 关系名兜底：中文事实下，若 relation_type 是拼音/英文样式（如 ALL_CAPS_XXX），统一回退中文名
            relation_type = new_dict.get('relation_type')
            fact_text = str(new_dict.get('fact') or '')
            if isinstance(relation_type, str):
                rt = relation_type.strip()
                has_zh_fact = re.search(r'[\u4e00-\u9fff]', fact_text) is not None
                has_zh_rt = re.search(r'[\u4e00-\u9fff]', rt) is not None
                looks_ascii_token = re.fullmatch(r'[A-Za-z0-9_\- ]+', rt) is not None
                if has_zh_fact and rt and (not has_zh_rt) and looks_ascii_token:
                    logger.warning(f"Normalizing non-Chinese relation_type '{rt}' to '相关'")
                    new_dict['relation_type'] = '相关'
            
            return new_dict
        return data

    def _normalize_indices(self, data: Any) -> Any:
        """
        自动处理 1-based 到 0-based 的 ID 平移。
        DeepSeek-V3 经常返回从 1 开始的 ID，而 Graphiti 期望从 0 开始。
        """
        if isinstance(data, dict):
            # 先处理列表项
            for key, value in data.items():
                if isinstance(value, list):
                    data[key] = self._normalize_list_indices(value)
            return data
        if isinstance(data, list):
            return self._normalize_list_indices(data)
        return data

    def _normalize_list_indices(self, items: list) -> list:
        if not items or not isinstance(items[0], dict):
            return items

        # 找出所有的 ID 字段
        node_id_fields = ['entity_id', 'id', 'node_id']
        edge_id_fields = ['source_entity_id', 'target_entity_id']
        
        all_ids = []
        for item in items:
            if not isinstance(item, dict): continue
            for f in node_id_fields + edge_id_fields:
                val = item.get(f)
                if isinstance(val, int):
                    all_ids.append(val)
        
        if not all_ids:
            return items
            
        min_id = min(all_ids)
        # 如果最小值是 1，说明很可能是 1-based，统一减 1 归一化到 0-based
        if min_id == 1:
            logger.error(f"Detected 1-based IDs (min={min_id}), shifting all IDs in this list by -1")
            for item in items:
                if not isinstance(item, dict): continue
                for f in node_id_fields + edge_id_fields:
                    if isinstance(item.get(f), int):
                        item[f] -= 1
        elif min_id > 1:
            # 极端情况：如果最小值大于 1，按最小值平移到 0
            logger.error(f"Detected high-start IDs (min={min_id}), shifting all IDs in this list to start at 0")
            for item in items:
                if not isinstance(item, dict): continue
                for f in node_id_fields + edge_id_fields:
                    if isinstance(item.get(f), int):
                        item[f] -= min_id

        return items

    def clean_json_text(self, text: str) -> str:
        # 移除 XML-like 标签 (如 <ENTITY>...</ENTITY>)
        text = re.sub(r'<[A-Z_]+>\s*', '', text)
        text = re.sub(r'</[A-Z_]+>\s*', '', text)
        # 移除 markdown 代码块
        text = re.sub(r'```json\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'```\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
        
        # 寻找第一个 [ 或 {
        match = re.search(r'(\[|\{)', text)
        if not match:
            return text
            
        start_idx = match.start()
        # 寻找对应的最后一个 ] 或 }
        # 这是一个简化处理，假设最后面的对应字符就是结束位置
        end_char = ']' if match.group(1) == '[' else '}'
        end_idx = text.rfind(end_char)
        
        if end_idx != -1 and end_idx > start_idx:
            return text[start_idx:end_idx+1]
        
        return text.strip()

    def safe_parse_json(self, text: str) -> Any:
        """尝试解析 JSON，如果失败则尝试 Python literal_eval（处理单引号字典）"""
        import ast
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # DeepSeek 有时候返回 Python dict 格式（单引号），尝试 ast.literal_eval
            try:
                result = ast.literal_eval(text)
                logger.error(f"Parsed response using ast.literal_eval (single-quote dict)")
                return result
            except (ValueError, SyntaxError):
                # 最后尝试：把单引号替换为双引号
                try:
                    fixed = text.replace("'", '"')
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    raise

    def _handle_json_response(self, response: Any) -> dict[str, Any]:
        # 普通 JSON 模式也进行清理
        if not hasattr(response, 'choices') or not response.choices:
            logger.error(f"Unexpected response format (no choices): {response}")
            raise Exception(f"Unexpected response format (no choices): {response}")
            
        content = response.choices[0].message.content or "{}"
        return json.loads(self.clean_json_text(content))

class SerialOpenAIEmbedder(OpenAIEmbedder):
    """使用真实 OpenAI Embedding API 的 Embedder，支持阿里云批量限制"""
    
    # 阿里云 DashScope 限制每批最多 10 个文本
    MAX_BATCH_SIZE = 10
    
    async def create_batch(self, texts: list[str]) -> list[list[float]]:
        """
        分批处理 embedding 请求，每批最多 MAX_BATCH_SIZE 个文本
        解决阿里云 DashScope API 批量限制问题
        """
        if len(texts) <= self.MAX_BATCH_SIZE:
            return await super().create_batch(texts)
        
        # 分批处理
        all_embeddings = []
        for i in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[i:i + self.MAX_BATCH_SIZE]
            batch_embeddings = await super().create_batch(batch)
            all_embeddings.extend(batch_embeddings)
            logger.info(f"Embedding batch {i // self.MAX_BATCH_SIZE + 1}: {len(batch)} texts")
        
        return all_embeddings

async def get_graphiti(settings: ZepEnvDep):
    # LLM 配置
    llm_config = LLMConfig(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.model_name
    )
    llm_client = ResilientOpenAIClient(config=llm_config)
    logger.error(f"Created Resilient LLM Client with base_url: {llm_config.base_url}, model: {llm_config.model}")

    # Embedding 配置
    emb_url = os.getenv("EMBEDDING_OPENAI_BASE_URL") or settings.openai_base_url
    emb_key = os.getenv("EMBEDDING_OPENAI_API_KEY") or settings.openai_api_key
    
    embed_config = OpenAIEmbedderConfig(
        api_key=emb_key,
        base_url=emb_url,
        embedding_model=settings.embedding_model_name or "text-embedding-3-small"
    )
    embedder = SerialOpenAIEmbedder(config=embed_config)
    logger.error(f"Created Embedder Client with base_url: {embed_config.base_url}, model: {embed_config.embedding_model}")

    client = ZepGraphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        llm_client=llm_client,
        embedder=embedder
    )

    try:
        yield client
    finally:
        await client.close()


async def initialize_graphiti(settings: ZepEnvDep):
    # LLM 配置
    llm_config = LLMConfig(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.model_name
    )
    llm_client = ResilientOpenAIClient(config=llm_config)
    logger.error(f"Initializing Graphiti with Resilient LLM base_url: {llm_config.base_url}")

    # Embedding 配置
    emb_url = os.getenv("EMBEDDING_OPENAI_BASE_URL") or settings.openai_api_key
    emb_key = os.getenv("EMBEDDING_OPENAI_API_KEY") or settings.openai_api_key
    
    embed_config = OpenAIEmbedderConfig(
        api_key=emb_key,
        base_url=emb_url,
        embedding_model=settings.embedding_model_name or "text-embedding-v4"
    )
    embedder = SerialOpenAIEmbedder(config=embed_config)
    logger.error(f"Initializing Graphiti with Embedder base_url: {embed_config.base_url}")

    client = ZepGraphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        llm_client=llm_client,
        embedder=embedder
    )

    logger.error("Building indices and constraints...")
    await client.build_indices_and_constraints()

    # 手动补齐 Vector Index (Graphiti Core 0.22 似乎未在 build_indices 中包含它)
    logger.error("Manually ensuring Vector Indexes...")
    vector_queries = [
        "CREATE VECTOR INDEX entity_name_embeddings IF NOT EXISTS FOR (n:Entity) ON (n.name_embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}",
        "CREATE VECTOR INDEX community_name_embeddings IF NOT EXISTS FOR (n:Community) ON (n.name_embedding) OPTIONS {indexConfig: {`vector.dimensions`: 1536, `vector.similarity_function`: 'cosine'}}"
    ]
    for q in vector_queries:
        try:
            await client.driver.execute_query(q)
        except Exception as e:
            logger.error(f"Failed to create vector index: {e}")

    await client.close()
    logger.error("Initialization Complete.")


def get_fact_result_from_edge(edge: EntityEdge):
    return FactResult(
        uuid=edge.uuid,
        name=edge.name,
        fact=edge.fact,
        valid_at=edge.valid_at,
        invalid_at=edge.invalid_at,
        created_at=edge.created_at,
        expired_at=edge.expired_at,
    )


ZepGraphitiDep = Annotated[ZepGraphiti, Depends(get_graphiti)]
