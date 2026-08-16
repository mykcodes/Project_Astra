from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.domain.entities import Entity

class TaskState(str, Enum):
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    RECOVERING = "RECOVERING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Intent(BaseModel):
    intent_id: str = Field(description="Unique identifier for the intent.")
    capability_id: str = Field(description="The abstract capability to invoke.")
    target: Optional[Entity] = Field(default=None, description="The semantic entity this intent acts upon.")
    parameters: Dict[str, Any] = Field(default_factory=dict, description="Parameters to pass to the capability.")

class Action(BaseModel):
    action_id: str = Field(description="Unique identifier for this action execution.")
    capability_id: str = Field(description="The capability being executed.")
    provider_id: str = Field(description="The selected provider performing the execution.")
    payload: Dict[str, Any] = Field(default_factory=dict, description="The concrete payload sent to the provider.")

class Task(BaseModel):
    task_id: str = Field(description="Unique identifier for the task.")
    description: str = Field(description="Human-readable description of the task.")
    intents: List[Intent] = Field(default_factory=list, description="The semantic intents comprising this task.")
    state: TaskState = Field(default=TaskState.PLANNING, description="Current lifecycle state of the task.")
    actions_taken: List[Action] = Field(default_factory=list, description="History of actions executed for this task.")

class Goal(BaseModel):
    goal_id: str = Field(description="Unique identifier for the goal.")
    objective: str = Field(description="The overarching objective requested by the user.")
    tasks: List[Task] = Field(default_factory=list, description="The sequence of tasks planned to achieve the goal.")
    is_complete: bool = Field(default=False, description="Whether the goal has been successfully achieved.")
