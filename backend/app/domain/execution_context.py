from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
from app.domain.goals import Goal, Intent
class ExecutionContext(BaseModel):
    execution_id: str = Field(description="Unique ID for this execution run")
    goal: Optional[Goal] = Field(default=None, description="The goal being executed")
    current_task_index: int = Field(default=0, description="Index of the currently executing task")
    completed_tasks: List[str] = Field(default_factory=list, description="IDs of completed tasks")
    pending_tasks: List[str] = Field(default_factory=list, description="IDs of pending tasks")
    
    browser_session_id: Optional[str] = Field(default=None, description="Active browser session ID")
    active_browser_identity: Optional[str] = Field(default=None, description="Canonical name of active browser (e.g. chrome, brave)")
    active_page_id: Optional[str] = Field(default=None, description="Active page ID")
    
    current_url: Optional[str] = Field(default=None, description="Current URL of the browser")
    current_title: Optional[str] = Field(default=None, description="Current title of the page")
    
    last_observation_id: Optional[str] = Field(default=None, description="ID of the last observation")
    last_action: Optional[Dict[str, Any]] = Field(default=None, description="The last action taken")
    last_verification: Optional[Dict[str, Any]] = Field(default=None, description="The last verification result")
    
    last_intent: Optional[Intent] = Field(default=None, description="The last executed semantic intent")
    retryable_intent: Optional[Intent] = Field(default=None, description="The most recent intent that can be retried")
    
    recovery_history: List[Dict[str, Any]] = Field(default_factory=list, description="History of recoveries")
    
    waiting_reason: Optional[str] = Field(default=None, description="Reason for WAITING_FOR_USER state")
    
    environment_snapshot: Dict[str, Any] = Field(default_factory=dict, description="Last known environment snapshot")
