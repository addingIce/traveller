import json
import os
import time
from fastapi import APIRouter, HTTPException, Request
from openai import AsyncOpenAI
from pydantic import BaseModel
from typing import List, Dict, Any

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
    try:
        client = request.app.state.zep
        if client is None:
            raise HTTPException(status_code=503, detail="Zep 服务未就绪")
        # 在 Zep CE v2 中，我们将 collection_name 映射为 session_id 来获取知识数据
        session_id = f"novel_{collection_name}"
        memory = await client.memory.get(session_id)
        
        facts = [f.fact for f in (memory.relevant_facts or [])]
        cache = request.app.state.graph_cache
        items = cache.get("items", {})
        now = int(time.time())
        ttl = cache.get("ttl_seconds", 300)
        cached = items.get(collection_name)
        if cached and not cached.get("dirty") and (now - cached.get("updated_at", 0) < ttl):
            return cached.get("data") or {"nodes": [], "edges": []}

        if mode == "facts":
            graph = {"nodes": _build_fact_nodes(facts), "edges": []}
        else:
            extracted = await _extract_graph_from_facts(facts)
            graph = _compose_graph(facts, extracted)

        items[collection_name] = {
            "data": graph,
            "updated_at": now,
            "dirty": False,
        }

        return graph
            
    except Exception as e:
        print(f"Graph get Error: {str(e)}")
        # 即使报错也返回空的，防止前端崩溃
        return {"nodes": [], "edges": []}
