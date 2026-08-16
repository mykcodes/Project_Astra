from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime, timezone
from pydantic import BaseModel, Field

class ExecutionEventType(str, Enum):
    GOAL_ACCEPTED = "GOAL_ACCEPTED"
    PLAN_CREATED = "PLAN_CREATED"
    TASK_STARTED = "TASK_STARTED"
    TASK_PROGRESS = "TASK_PROGRESS"
    TASK_COMPLETED = "TASK_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    OBSERVATION_RECEIVED = "OBSERVATION_RECEIVED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_COMPLETED = "VERIFICATION_COMPLETED"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_COMPLETED = "RECOVERY_COMPLETED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    PERMISSION_REQUIRED = "PERMISSION_REQUIRED"
    GOAL_COMPLETED = "GOAL_COMPLETED"
    GOAL_FAILED = "GOAL_FAILED"
    ASSISTANT_RESPONSE = "ASSISTANT_RESPONSE"

class ExecutionEvent(BaseModel):
    event_type: ExecutionEventType = Field(description="The type of execution event.")
    execution_id: str = Field(description="Unique ID for this overall execution run.")
    goal_id: Optional[str] = Field(default=None, description="The associated Goal ID.")
    task_id: Optional[str] = Field(default=None, description="The associated Task ID.")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="When the event occurred.")
    state: str = Field(description="Internal machine-readable state of the event.")
    progress_label: str = Field(description="Human-readable progress label (e.g. 'Opening browser', 'Searching').")
    payload: Optional[Dict[str, Any]] = Field(default=None, description="Optional payload containing event specifics (e.g., text for assistant response, or error details).")

    def to_sse_json(self) -> str:
        return self.model_dump_json()
