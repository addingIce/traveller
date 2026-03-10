from fastapi import APIRouter
from . import graph, chat

api_router = APIRouter()
api_router.include_router(graph.router, prefix="/graph", tags=["Knowledge Graph"])
api_router.include_router(chat.router, prefix="/chat", tags=["Director AI Chat"])
