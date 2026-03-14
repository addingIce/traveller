from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum

class DirectorMode(str, Enum):
    SANDBOX = "SANDBOX"
    CONVERGENCE = "CONVERGENCE"

class IntentSummary(BaseModel):
    action: Optional[str] = None
    dialogue: Optional[str] = None
    thought: Optional[str] = None
    intensity: Optional[int] = 3
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

class WorldImpact(BaseModel):
    world_state_changed: bool
    reason: Optional[str] = None

class ChatRequest(BaseModel):
    session_id: str
    novel_id: str
    message: str
    mode: Optional[DirectorMode] = DirectorMode.SANDBOX

class ChatResponse(BaseModel):
    story_text: str
    user_intent_summary: IntentSummary
    world_impact: WorldImpact
    ui_hints: List[str]
    reached_waypoints: Optional[List[str]] = Field(default_factory=list)

class SessionCreate(BaseModel):
    novel_id: str
    user_id: str
    session_name: Optional[str] = "新的冒险"
    start_chapter_id: Optional[str] = None

class SessionInfo(BaseModel):
    session_id: str
    novel_id: str
    user_id: str
    session_name: str
    created_at: str
    last_interaction_at: Optional[str] = None
    parent_session_id: Optional[str] = None
    is_root: bool = False

class BookmarkCreate(BaseModel):
    name: str
    description: Optional[str] = None

class BookmarkInfo(BaseModel):
    id: str
    session_id: str
    name: str
    description: Optional[str] = None
    created_at: str
    checkpoint_id: str # Zep message UUID or sequence

class BranchRequest(BaseModel):
    bookmark_id: str # From which bookmark to branch
    new_session_name: Optional[str] = None

class ChapterInfo(BaseModel):
    id: str
    title: str
    content_preview: str
    order: int

class WaypointStatus(BaseModel):
    title: str
    description: str
    requirement: Optional[str] = None
    order: Optional[int] = None
    category: Optional[str] = None
    reached: bool = False
    reached_at: Optional[str] = None
