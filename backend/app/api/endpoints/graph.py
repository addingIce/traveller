import json
import os
import time
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
    session_id = f"novel_{collection_name}"
    try:
        # 0. 尝试从 Neo4j 直接拉取已持久化的实体和关系
        driver = getattr(request.app.state, "neo4j_driver", None)
        if driver:
            async with driver.session() as session:
                # 获取实体节点
                node_query = "MATCH (n:Entity {group_id: $group_id}) RETURN n.uuid as uuid, n.name as name, labels(n) as labels"
                node_result = await session.run(node_query, group_id=session_id)
                nodes = []
                async for record in node_result:
                    nodes.append({
                        "id": record["uuid"],
                        "label": record["name"],
                        "type": record["labels"][0] if record["labels"] else "concept"
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
                    print(f"Graph retrieved from Neo4j for {session_id}: {len(nodes)} nodes, {len(edges)} edges")
                    return {"nodes": nodes, "edges": edges}

        # 1. 如果 Neo4j 没数据，或者模式要求使用 facts 提取，备选走 Zep Facts 路径
        client = request.app.state.zep
        if client is None:
            return {"nodes": [], "edges": []}
            
        memory = await client.memory.get(session_id)
        facts = [f.fact for f in (memory.relevant_facts or [])]
        
        if not facts:
            return {"nodes": [], "edges": []}

        if mode == "facts":
            graph = {"nodes": _build_fact_nodes(facts), "edges": []}
        else:
            extracted = await _extract_graph_from_facts(facts)
            graph = _compose_graph(facts, extracted)

        return graph
            
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
            WHERE n.name CONTAINS $query OR n.summary CONTAINS $query
            RETURN n.uuid as uuid, n.name as name, labels(n) as labels
            LIMIT 10
            """
            result = await session.run(cypher, group_id=session_id, query=query or "")
            async for record in result:
                results["nodes"].append({
                    "id": record["uuid"],
                    "label": record["name"],
                    "type": record["labels"][0] if record["labels"] else "concept"
                })
        
        # 2. 语义搜索 (通过 Zep 检索 Facts)
        client = request.app.state.zep
        if client and query:
            # Zep 原生搜索其关联的 Facts
            search_res = await client.memory.search(session_id, text=query, limit=5)
            for fact in (search_res.facts or []):
                results["facts"].append(fact.fact)

    except Exception as e:
        print(f"Search Error: {e}")
    
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
