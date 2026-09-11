from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, field_validator
from app.domain.entities import Entity, TriState

class SemanticAction(str, Enum):
    NAVIGATE = "NAVIGATE"
    SEARCH = "SEARCH"
    PLAY = "PLAY"
    PAUSE = "PAUSE"
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    MOVE_MOUSE = "MOVE_MOUSE"
    INPUT = "INPUT"
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    FOCUS = "FOCUS"
    RETRY = "RETRY"
    REPEAT = "REPEAT"
    CONTINUE = "CONTINUE"

class TargetType(str, Enum):
    APPLICATION = "APPLICATION"
    WEBSITE = "WEBSITE"
    PAGE = "PAGE"
    SEARCH_BOX = "SEARCH_BOX"
    SEARCH_RESULT = "SEARCH_RESULT"
    MEDIA = "MEDIA"
    BUTTON = "BUTTON"
    LINK = "LINK"
    INPUT = "INPUT"
    ORDINAL_TARGET = "ORDINAL_TARGET"
    URL_OR_SITE = "URL_OR_SITE"
    COORDINATE = "COORDINATE"
    UNKNOWN = "UNKNOWN"

class TargetOrdinal(str, Enum):
    FIRST = "FIRST"
    SECOND = "SECOND"
    THIRD = "THIRD"
    LAST = "LAST"
    NONE = "NONE"

class TaskState(str, Enum):
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class GoalState(str, Enum):
    INTENT_RECEIVED = "INTENT_RECEIVED"
    GOAL_FORMULATED = "GOAL_FORMULATED"
    PLAN_CREATED = "PLAN_CREATED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    WAITING_FOR_USER = "WAITING_FOR_USER"

class FailureClass(str, Enum):
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    STALE_TARGET = "STALE_TARGET"
    PAGE_CHANGED = "PAGE_CHANGED"
    NAVIGATION_TIMEOUT = "NAVIGATION_TIMEOUT"
    BROWSER_CLOSED = "BROWSER_CLOSED"
    CAPTCHA_DETECTED = "CAPTCHA_DETECTED"
    POPUP_OPENED = "POPUP_OPENED"
    CLICK_NO_EFFECT = "CLICK_NO_EFFECT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    UNKNOWN = "UNKNOWN"
    EXECUTION_FAILED = "EXECUTION_FAILED"

class Intent(BaseModel):
    intent_id: str = Field(description="Unique identifier for the intent.")
    action: SemanticAction = Field(description="The semantic action to perform.")
    target: Optional[str] = Field(default=None, description="The specific target name or value (e.g. YouTube, Baby).")
    target_type: TargetType = Field(default=TargetType.UNKNOWN, description="The semantic type of the target.")
    ordinal: TargetOrdinal = Field(default=TargetOrdinal.NONE, description="Ordinal resolution if applicable.")
    query: Optional[str] = Field(default=None, description="Search query or input text.")
    browser: Optional[str] = Field(default=None, description="Browser context if required.")
    page_context: Optional[str] = Field(default=None, description="Expected page context.")
    capability_id: str = Field(default="", description="The abstract capability to invoke (filled by compiler).")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters to pass to the capability (filled by compiler).")

class ActionExpectation(BaseModel):
    expected_outcome: str = Field(description="Description of what should happen")
    expected_state_changes: Dict[str, Any] = Field(default_factory=dict, description="State keys and their expected new values")

class VerificationResult(BaseModel):
    verified: TriState = Field(description="Whether the requested state was verified (TRUE, FALSE, UNKNOWN)")
    confidence: float = Field(default=1.0)
    verification_type: str = Field(default="UNKNOWN")
    expected_state: Optional[str] = None
    actual_state: Optional[str] = None
    evidence: str = Field(default="")
    observation_id: Optional[str] = None
    failure_code: Optional[FailureClass] = None

    @field_validator('verified', mode='before')
    def coerce_boolean(cls, v):
        if v is True:
            return TriState.TRUE
        if v is False:
            return TriState.FALSE
        return v

class Action(BaseModel):
    action_id: str = Field(description="Unique identifier for this action execution.")
    capability_id: str = Field(description="The capability being executed.")
    provider_id: str = Field(description="The selected provider performing the execution.")
    payload: Dict[str, Any] = Field(default_factory=dict, description="The concrete payload sent to the provider.")
    verification_result: Optional[VerificationResult] = Field(default=None, description="The result of the verification.")

class Task(BaseModel):
    task_id: str = Field(description="Unique identifier for the task.")
    description: str = Field(description="Human-readable description of the task.")
    intents: List[Intent] = Field(default_factory=list, description="The semantic intents comprising this task.")
    prerequisites: List[str] = Field(default_factory=list, description="IDs of tasks that must complete before this one.")
    expected_outcome: Optional[str] = Field(default=None, description="Expected outcome of the task.")
    state: TaskState = Field(default=TaskState.PLANNING, description="Current lifecycle state of the task.")
    actions_taken: List[Action] = Field(default_factory=list, description="History of actions executed for this task.")

class Goal(BaseModel):
    goal_id: str = Field(description="Unique identifier for the goal.")
    objective: str = Field(description="The overarching objective requested by the user.")
    tasks: List[Task] = Field(default_factory=list, description="The sequence of tasks planned to achieve the goal.")
    state: GoalState = Field(default=GoalState.INTENT_RECEIVED, description="Current lifecycle state of the goal.")
    is_complete: bool = Field(default=False, description="Whether the goal has been successfully achieved.")
