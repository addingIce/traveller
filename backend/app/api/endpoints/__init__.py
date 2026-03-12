from fastapi import APIRouter
from . import graph, chat, novels

api_router = APIRouter()
api_router.include_router(graph.router, prefix="/graph", tags=["Knowledge Graph"])
api_router.include_router(chat.router, prefix="/chat", tags=["Director AI Chat"])
api_router.include_router(novels.router, prefix="/novels", tags=["Novel Management"])
