from fastapi import APIRouter, HTTPException, Request, status
from typing import List
from app.models.schemas import SessionCreate, SessionInfo, BookmarkCreate, BookmarkInfo, BranchRequest, ChapterInfo
from app.services.session_service import SessionService

router = APIRouter()

@router.post("", response_model=SessionInfo, status_code=status.HTTP_201_CREATED)
async def create_session(req: SessionCreate, request: Request):
    if not request.app.state.zep or not request.app.state.neo4j_driver:
        raise HTTPException(status_code=503, detail="Infrastructure not ready")
    service = SessionService(request.app.state.zep, request.app.state.neo4j_driver)
    try:
        session_data = await service.create_session(req.novel_id, req.user_id, req.session_name)
        return SessionInfo(**session_data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{novel_id}", response_model=List[SessionInfo])
async def list_sessions(novel_id: str, request: Request):
    service = SessionService(request.app.state.zep, request.app.state.neo4j_driver)
    try:
        sessions = await service.list_sessions(novel_id)
        return [SessionInfo(**s) for s in sessions]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{session_id}/bookmark", response_model=BookmarkInfo)
async def create_bookmark(session_id: str, req: BookmarkCreate, request: Request):
    service = SessionService(request.app.state.zep, request.app.state.neo4j_driver)
    try:
        bookmark = await service.create_bookmark(session_id, req.name, req.description)
        return BookmarkInfo(**bookmark)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{session_id}/bookmarks", response_model=List[BookmarkInfo])
async def list_bookmarks(session_id: str, request: Request):
    service = SessionService(request.app.state.zep, request.app.state.neo4j_driver)
    try:
        bookmarks = await service.list_bookmarks(session_id)
        return [BookmarkInfo(**b) for b in bookmarks]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{session_id}/branch", response_model=SessionInfo)
async def branch_session(session_id: str, req: BranchRequest, request: Request):
    service = SessionService(request.app.state.zep, request.app.state.neo4j_driver)
    try:
        new_session = await service.branch_from_bookmark(session_id, req.bookmark_id, req.new_session_name)
        return SessionInfo(**new_session)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{novel_id}/chapters", response_model=List[ChapterInfo])
async def get_chapters(novel_id: str, request: Request):
    service = SessionService(request.app.state.zep, request.app.state.neo4j_driver)
    try:
        chapters = await service.extract_chapters(novel_id)
        return [ChapterInfo(**c) for c in chapters]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
