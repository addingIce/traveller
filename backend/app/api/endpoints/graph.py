from fastapi import APIRouter, HTTPException
import os
from pydantic import BaseModel
from typing import List, Dict, Any
from zep_python import ZepClient

router = APIRouter()

# Get variables locally since global dependency injection might be complex for a simple prototype
ZEP_API_URL = os.getenv("ZEP_API_URL", "http://localhost:8000")
ZEP_API_KEY = os.getenv("ZEP_API_KEY", "")

class GraphResponse(BaseModel):
    nodes: List[Dict[str, Any]]
    edges: List[Dict[str, Any]]

@router.get("/{collection_name}", response_model=GraphResponse)
async def get_knowledge_graph(collection_name: str):
    """
    获取指定小说的知识图谱 (节点和关系边缘)
    """
    try:
        async with ZepClient(base_url=ZEP_API_URL, api_key=ZEP_API_KEY) as zep_client:
            graph_data = await zep_client.graph.get_graph(collection_name)
            
            if not graph_data or not graph_data.nodes:
                return {"nodes": [], "edges": []}
            
            # Format nodes and edges for the frontend (like AntV G6 or ECharts)
            nodes = [{"id": n.name, "label": n.name, "type": n.type} for n in graph_data.nodes]
            edges = [{"source": e.source, "target": e.target, "label": e.label} for e in graph_data.edges]
            
            return {"nodes": nodes, "edges": edges}
            
    except Exception as e:
        print(f"Graph get Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"无法获取图谱: {str(e)}")
