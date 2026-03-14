import json
import os
import time
import unicodedata
from fastapi import APIRouter, HTTPException, Request
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

router = APIRouter()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
MODEL_PARSER = os.getenv("MODEL_PARSER", "gpt-4o-mini")
# Trigger hot reload for new .env variables

aclient = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL
)

class GraphResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

class SearchResult(BaseModel):
    query: str
    nodes: List[Dict[str, Any]]
    facts: List[str] = []

class NodeDetail(BaseModel):
    id: str
    label: str
    type: str
    summary: Optional[str] = None

def _build_fact_nodes(facts: List[str]) -> List[Dict[str, Any]]:
    nodes = []
    for i, fact in enumerate(facts):
        nodes.append({
            "id": f"fact:{i}",
            "label": (fact[:20] + "...") if len(fact) > 20 else fact,
            "full_text": fact,
            "type": "fact",
        })
    return nodes

def _slugify(name: str) -> str:
    return "".join(ch for ch in name.lower().strip().replace(" ", "_") if ch.isalnum() or ch in "_:-")


def _normalize_entity_name(name: str) -> str:
    normalized = unicodedata.normalize("NFKC", name or "")
    return normalized.strip().lower()


def _is_better_graph_node(candidate: Dict[str, Any], current: Dict[str, Any]) -> bool:
    candidate_score = (
        int(candidate.get("rel_count", 0)),
        len((candidate.get("summary") or "").strip()),
    )
    current_score = (
        int(current.get("rel_count", 0)),
        len((current.get("summary") or "").strip()),
    )
    return candidate_score > current_score


def _dedupe_graph_payload(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    winners_by_name: Dict[str, Dict[str, Any]] = {}
    uuid_alias: Dict[str, str] = {}
    passthrough_nodes: List[Dict[str, Any]] = []
    duplicate_hits = 0

    for node in nodes:
        key = _normalize_entity_name(node.get("label", ""))
        if not key:
            uuid_alias[node["id"]] = node["id"]
            passthrough_nodes.append(node)
            continue
        current = winners_by_name.get(key)
        if current is None:
            winners_by_name[key] = node
            uuid_alias[node["id"]] = node["id"]
            continue
        duplicate_hits += 1
        if _is_better_graph_node(node, current):
            uuid_alias[current["id"]] = node["id"]
            winners_by_name[key] = node
            uuid_alias[node["id"]] = node["id"]
        else:
            uuid_alias[node["id"]] = current["id"]

    deduped_nodes = [
        {"id": node["id"], "label": node["label"], "type": node["type"]}
        for node in winners_by_name.values()
    ]
    deduped_nodes.extend(
        [{"id": node["id"], "label": node["label"], "type": node["type"]} for node in passthrough_nodes]
    )
    deduped_edges: List[Dict[str, Any]] = []
    edge_seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        source = uuid_alias.get(edge["source"], edge["source"])
        target = uuid_alias.get(edge["target"], edge["target"])
        if source == target:
            continue
        label = edge.get("label") or "related"
        edge_key = (source, target, label)
        if edge_key in edge_seen:
            continue
        edge_seen.add(edge_key)
        deduped_edges.append(
            {
                "id": edge["id"],
                "source": source,
                "target": target,
                "label": label,
            }
        )

    return {
        "nodes": deduped_nodes,
        "edges": deduped_edges,
        "duplicate_hits": duplicate_hits,
    }


def _dedupe_search_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    passthrough: List[Dict[str, Any]] = []
    for node in nodes:
        key = _normalize_entity_name(node.get("label", ""))
        if not key:
            passthrough.append(node)
            continue
        if key in by_name:
            continue
        by_name[key] = node
    return list(by_name.values()) + passthrough

async def _extract_graph_from_facts(facts: List[str]) -> Dict[str, Any]:
    if not facts or not OPENAI_API_KEY:
        return {"entities": [], "relations": []}

    fact_lines = "\n".join([f"[{i}] {f}" for i, f in enumerate(facts)])
    system_prompt = (
        "你是知识图谱抽取器。根据事实列表抽取实体与关系，输出严格 JSON 对象。"
        "要求：所有输出内容（实体名、关系描述、类型名等）必须使用与原文完全一致的语言（中文）。"
        "不要将中文翻译成英文，例如不要将'同学'翻译成'classmate'。"
        "实体包含 name 与 type（person/place/org/item/concept 之一）。"
        "关系包含 source/target/type 以及 evidence_fact_indexes（数组，引用事实索引）。"
        "仅输出 JSON，不要 Markdown。"
    )
    response = await aclient.chat.completions.create(
        model=MODEL_PARSER,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": fact_lines},
        ],
        temperature=0.2,
        extra_body={"enable_thinking": False},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except Exception:
        data = {"entities": [], "relations": []}
    return {
        "entities": data.get("entities") or [],
        "relations": data.get("relations") or [],
    }

def _compose_graph(facts: List[str], extracted: Dict[str, Any]) -> Dict[str, Any]:
    nodes = _build_fact_nodes(facts)
    edges: List[Dict[str, Any]] = []

    entity_nodes: Dict[str, Dict[str, Any]] = {}
    for ent in extracted.get("entities", []):
        name = (ent or {}).get("name")
        if not name:
            continue
        ent_id = f"entity:{_slugify(name)}"
        if ent_id in entity_nodes:
            continue
        entity_nodes[ent_id] = {
            "id": ent_id,
            "label": name,
            "type": (ent or {}).get("type") or "concept",
        }

    nodes.extend(entity_nodes.values())

    for rel in extracted.get("relations", []):
        src_name = (rel or {}).get("source")
        tgt_name = (rel or {}).get("target")
        if not src_name or not tgt_name:
            continue
        src_id = f"entity:{_slugify(src_name)}"
        tgt_id = f"entity:{_slugify(tgt_name)}"
        if src_id not in entity_nodes or tgt_id not in entity_nodes:
            continue
        edge_id = f"rel:{_slugify(src_name)}:{_slugify(tgt_name)}:{_slugify((rel or {}).get('type') or 'related')}"
        edges.append({
            "id": edge_id,
            "source": src_id,
            "target": tgt_id,
            "type": (rel or {}).get("type") or "related",
            "label": (rel or {}).get("type") or "related",
        })

        evidence = (rel or {}).get("evidence_fact_indexes") or []
        for idx in evidence:
            if isinstance(idx, int) and 0 <= idx < len(facts):
                edges.append({
                    "id": f"mentions:fact:{idx}:{src_id}",
                    "source": f"fact:{idx}",
                    "target": src_id,
                    "type": "mentions",
                    "label": "mentions",
                })
                edges.append({
                    "id": f"mentions:fact:{idx}:{tgt_id}",
                    "source": f"fact:{idx}",
                    "target": tgt_id,
                    "type": "mentions",
                    "label": "mentions",
                })

    return {"nodes": nodes, "edges": edges}

@router.get("/{collection_name}", response_model=GraphResponse)
async def get_knowledge_graph(collection_name: str, request: Request, mode: str = "auto"):
    """
    获取指定小说的知识图谱 (节点和关系边缘)
    """
    # 检查 collection_name 是否已经以 novel_ 开头
    if collection_name.startswith("novel_"):
        session_id = collection_name
    else:
        session_id = f"novel_{collection_name}"
    try:
        # 0. 尝试从 Neo4j 直接拉取已持久化的实体和关系
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver:
            async with driver.session() as session:
                # 获取实体节点
                node_query = """
                MATCH (n:Entity {group_id: $group_id})
                OPTIONAL MATCH (n)-[r]-()
                RETURN
                    n.uuid as uuid,
                    n.name as name,
                    n.summary as summary,
                    labels(n) as labels,
                    count(r) as rel_count
                """
                node_result = await session.run(node_query, group_id=session_id)
                nodes = []
                async for record in node_result:
                    nodes.append({
                        "id": record["uuid"],
                        "label": record["name"],
                        "type": record["labels"][0] if record["labels"] else "concept",
                        "summary": record["summary"] or "",
                        "rel_count": int(record["rel_count"] or 0),
                    })
                
                # 获取关系边
                edge_query = """
                MATCH (n:Entity {group_id: $group_id})-[r:RELATES_TO]->(m:Entity {group_id: $group_id}) 
                RETURN r.uuid as uuid, n.uuid as source, m.uuid as target, r.fact as fact, r.name as name
                """
                edge_result = await session.run(edge_query, group_id=session_id)
                edges = []
                async for record in edge_result:
                    edges.append({
                        "id": record["uuid"],
                        "source": record["source"],
                        "target": record["target"],
                        "label": record["name"] or record["fact"] or "related"
                    })
                
                if nodes:
                    deduped = _dedupe_graph_payload(nodes, edges)
                    if deduped["duplicate_hits"] > 0:
                        print(
                            f"[WARNING] Duplicate entity names detected in graph payload: "
                            f"group={session_id}, duplicates={deduped['duplicate_hits']}"
                        )
                    print(
                        f"Graph retrieved from Neo4j for {session_id}: "
                        f"{len(deduped['nodes'])} nodes, {len(deduped['edges'])} edges"
                    )
                    return {"nodes": deduped["nodes"], "edges": deduped["edges"]}

        # 1. 如果 Neo4j 没数据，或者模式要求使用 facts 提取，备选走 Zep Facts 路径
        client = getattr(request.app.state, "zep", None)
        if client is None:
            return {"nodes": [], "edges": []}
            
        # 如果 Neo4j 为空，且手动指定了 facts 模式，则走 Facts 路径（M0 保留逻辑）
        if mode == "facts":
            memory = await client.memory.get(session_id)
            facts = [f.fact for f in (memory.relevant_facts or [])]
            return {"nodes": _build_fact_nodes(facts), "edges": []}

        # 默认不自动降级到 LLM 抽取，尊崇用户“物理图谱”一致性要求
        return {"nodes": [], "edges": []}
            
    except Exception as e:
        print(f"Graph get Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"nodes": [], "edges": []}

@router.get("/{collection_name}/search", response_model=SearchResult)
async def search_graph_api(collection_name: str, query: str, request: Request):
    """
    语义/关键词搜索节点和事实
    """
    # 检查 collection_name 是否已经以 novel_ 开头
    if collection_name.startswith("novel_"):
        session_id = collection_name
    else:
        session_id = f"novel_{collection_name}"
    
    driver = getattr(request.app.state, "neo4j_driver", None)
    results = {"query": query, "nodes": [], "facts": []}
    
    if not driver:
        return results

    try:
        async with driver.session() as session:
            # 1. 关键词/名称 匹配 (Cypher)
            cypher = """
            MATCH (n:Entity {group_id: $group_id})
            WHERE n.name CONTAINS $search_query OR n.summary CONTAINS $search_query
            RETURN n.uuid as uuid, n.name as name, labels(n) as labels
            LIMIT 10
            """
            result = await session.run(cypher, group_id=session_id, search_query=query or "")
            async for record in result:
                results["nodes"].append({
                    "id": record["uuid"],
                    "label": record["name"],
                    "type": record["labels"][0] if record["labels"] else "concept"
                })
            deduped_nodes = _dedupe_search_nodes(results["nodes"])
            if len(deduped_nodes) != len(results["nodes"]):
                print(
                    f"[WARNING] Duplicate entity names detected in search payload: "
                    f"group={session_id}, before={len(results['nodes'])}, after={len(deduped_nodes)}"
                )
            results["nodes"] = deduped_nodes
        
        # 2. 语义搜索 (通过 Zep 检索 Facts)
        client = request.app.state.zep
        if client and query:
            try:
                # 获取 session 的 memory，包含相关 facts
                memory = await client.memory.get(session_id)
                # 简单的文本匹配过滤相关 facts
                all_facts = memory.relevant_facts or []
                query_lower = query.lower()
                matching_facts = [
                    f.fact for f in all_facts
                    if query_lower in f.fact.lower()
                ]
                results["facts"] = matching_facts[:5]  # 限制返回 5 个
            except Exception as zep_error:
                # Zep 搜索失败不影响 Neo4j 搜索结果
                print(f"[WARNING] Zep search failed: {zep_error}")

    except Exception as e:
        print(f"[ERROR] Search Error: {e}")
        import traceback
        traceback.print_exc()
    
    return results

@router.get("/node/{uuid}", response_model=NodeDetail)
async def get_node_detail(uuid: str, request: Request):
    """
    获取单个节点的详细属性，包括 AI 摘要
    """
    driver = getattr(request.app.state, "neo4j_driver", None)
    if not driver:
        raise HTTPException(status_code=503, detail="Database not ready")
        
    async with driver.session() as session:
        query = "MATCH (n:Entity {uuid: $uuid}) RETURN n.uuid as id, n.name as label, n.summary as summary, labels(n)[0] as type"
        result = await session.run(query, uuid=uuid)
        record = await result.single()
        if not record:
            raise HTTPException(status_code=404, detail="Node not found")
        return NodeDetail(
            id=record["id"],
            label=record["label"],
            type=record["type"] or "Entity",
            summary=record["summary"]
        )
