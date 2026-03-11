import asyncio
import logging
import os
import re
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

_LLM_MAX_CONCURRENCY = int(os.getenv("GRAPHITI_LLM_MAX_CONCURRENCY", "1"))
_LLM_MIN_INTERVAL = float(os.getenv("GRAPHITI_LLM_MIN_INTERVAL", "0"))
_llm_semaphore = asyncio.Semaphore(_LLM_MAX_CONCURRENCY)
_last_llm_call: ContextVar[float] = ContextVar("_last_llm_call", default=0.0)

def _utc_now_monotonic() -> float:
    return asyncio.get_running_loop().time()


class ZepGraphiti(Graphiti):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
                    new_dict[k] = json.dumps(v, ensure_ascii=True)
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
    async def _generate_response(
        self,
        messages: list[Any],
        response_model: type[BaseModel] | None = None,
        max_tokens: int = 8192,
        model_size: Any = None,
    ) -> dict[str, Any]:
        # 记录当前的 response_model 以便在 _handle_structured_response 中使用
        token = _current_response_model.set(response_model)
        try:
            async with _llm_semaphore:
                if _LLM_MIN_INTERVAL > 0:
                    last = _last_llm_call.get()
                    now = _utc_now_monotonic()
                    wait = _LLM_MIN_INTERVAL - (now - last)
                    if wait > 0:
                        await asyncio.sleep(wait)

                # 当前网关对 structured output 兼容性不稳定，强制走普通 completion。
                # 结构化输出路径保留在下方注释，便于后续恢复。
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
                data = json.loads(clean_content)
                data = self.normalize_data(data)
                data = self._reindex_entity_ids(data)
                if isinstance(data, list):
                    response_model = _current_response_model.get()
                    if response_model:
                        fields = list(response_model.model_fields.keys())
                        if fields:
                            data = {fields[0]: data}
                    else:
                        data = {"extracted_entities": data}
                data = _sanitize_payload(data)
                _last_llm_call.set(_utc_now_monotonic())
                return data

                # --- 结构化输出路径（保留备用） ---
                # result = await super()._generate_response(
                #     messages,
                #     response_model=response_model,
                #     max_tokens=max_tokens,
                #     model_size=model_size,
                # )
                # _last_llm_call.set(_utc_now_monotonic())
                # return result
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
                logger.info(f"Auto-wrapping list response into field: {fields[0]}")
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
                    'entity': 'name',
                    'node': 'name',
                    'entity_name': 'name',
                    'node_name': 'name',
                    'fact_content': 'fact',
                    'relationship': 'fact',
                    'relation': 'fact',
                    'description': 'fact',
                    'source_node': 'source_node_uuid',
                    'target_node': 'target_node_uuid',
                }
                if k in mapping:
                    new_key = mapping[k]
                
                new_dict[new_key] = self.normalize_data(v)
            return new_dict
        return data

    def _reindex_entity_ids(self, data: Any) -> Any:
        """
        强制按数组位置重新绑定实体 ID (0-based)。
        DeepSeek-V3 等模型返回节点 ID 从 1 开始，但边的引用 (subject_id/object_id)
        却从 0 开始，导致 Graphiti 内部 ID 匹配全部失败。
        此方法统一将所有实体节点的 ID 重置为基于数组下标的 0-based 索引。
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, list):
                    data[key] = self._reindex_list_if_entities(value)
            return data
        if isinstance(data, list):
            return self._reindex_list_if_entities(data)
        return data

    def _reindex_list_if_entities(self, items: list) -> list:
        """对列表中的字典项，如果看起来像实体节点，则按位置重新分配 ID。"""
        if not items or not isinstance(items[0], dict):
            return items

        first = items[0]
        # 只对看起来像实体节点的列表进行重索引（同时具有 ID 字段和名称字段）
        has_name = any(k in first for k in ['name', 'entity_name', 'node_name'])
        id_field = None
        for field in ['entity_id', 'id', 'node_id']:
            if field in first:
                id_field = field
                break

        if id_field and has_name:
            for idx, item in enumerate(items):
                if isinstance(item, dict) and id_field in item:
                    old_id = item[id_field]
                    item[id_field] = idx
                    if old_id != idx:
                        logger.info(f"Reindexed entity {id_field}: {old_id} -> {idx}")

        return items

    def clean_json_text(self, text: str) -> str:
        # 移除 markdown 代码块
        text = re.sub(r'```json\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
        text = re.sub(r'```\s*(.*?)\s*```', r'\1', text, flags=re.DOTALL)
        
        # 提取第一个 { 或 [ 到最后一个 } 或 ] 之间的内容
        first_brace = text.find('{')
        last_brace = text.rfind('}')
        first_bracket = text.find('[')
        last_bracket = text.rfind(']')
        
        start = -1
        end = -1
        
        if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
            start = first_brace
            end = last_brace
        elif first_bracket != -1:
            start = first_bracket
            end = last_bracket
            
        if start != -1 and end != -1:
            return text[start:end+1]
        return text

    def _handle_json_response(self, response: Any) -> dict[str, Any]:
        # 普通 JSON 模式也进行清理
        if not hasattr(response, 'choices') or not response.choices:
            logger.error(f"Unexpected response format (no choices): {response}")
            raise Exception(f"Unexpected response format (no choices): {response}")
            
        content = response.choices[0].message.content or "{}"
        return json.loads(self.clean_json_text(content))

class SerialOpenAIEmbedder(OpenAIEmbedder):
    async def create(self, *args, **kwargs):
        # 已经确认 Embedding 模型无并发限制，直接调用
        return await super().create(*args, **kwargs)
            
    async def create_batch(self, input_data: list[str], *args, **kwargs) -> list[list[float]]:
        # 记录空字符串的位置，并对非空字符串进行计算
        valid_indices = []
        valid_input = []
        for i, text in enumerate(input_data):
            if text and text.strip():
                valid_indices.append(i)
                valid_input.append(text)
        
        result = [[] for _ in range(len(input_data))]
        
        if valid_input:
            # ModelScope 需要 input.texts 为有效文字列表
            batch_result = await super().create_batch(valid_input, *args, **kwargs)
            
            # 将有效结果映射回原来的对应下标
            for idx, valid_idx in enumerate(valid_indices):
                result[valid_idx] = batch_result[idx]
        return result

async def get_graphiti(settings: ZepEnvDep):
    # LLM 配置
    llm_config = LLMConfig(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.model_name
    )
    llm_client = ResilientOpenAIClient(config=llm_config)
    logger.info(f"Created Resilient LLM Client with base_url: {llm_config.base_url}, model: {llm_config.model}")

    # Embedding 配置
    emb_url = os.getenv("EMBEDDING_OPENAI_BASE_URL") or settings.openai_base_url
    emb_key = os.getenv("EMBEDDING_OPENAI_API_KEY") or settings.openai_api_key
    
    embed_config = OpenAIEmbedderConfig(
        api_key=emb_key,
        base_url=emb_url,
        embedding_model=settings.embedding_model_name or "text-embedding-3-small"
    )
    embedder = SerialOpenAIEmbedder(config=embed_config)
    logger.info(f"Created Embedder Client with base_url: {embed_config.base_url}, model: {embed_config.embedding_model}")

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
    logger.info(f"Initializing Graphiti with Resilient LLM base_url: {llm_config.base_url}")

    # Embedding 配置
    emb_url = os.getenv("EMBEDDING_OPENAI_BASE_URL") or settings.openai_base_url
    emb_key = os.getenv("EMBEDDING_OPENAI_API_KEY") or settings.openai_api_key
    
    embed_config = OpenAIEmbedderConfig(
        api_key=emb_key,
        base_url=emb_url,
        embedding_model=settings.embedding_model_name or "text-embedding-3-small"
    )
    embedder = SerialOpenAIEmbedder(config=embed_config)
    logger.info(f"Initializing Graphiti with Embedder base_url: {embed_config.base_url}")

    client = ZepGraphiti(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        llm_client=llm_client,
        embedder=embedder
    )

    await client.build_indices_and_constraints()


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
