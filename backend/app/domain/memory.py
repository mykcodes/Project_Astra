from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from app.domain.entities import Entity, Observation
from app.domain.goals import Goal, Task

class RecoveryStrategy(str, Enum):
    REFRESH_OBSERVATION = "REFRESH_OBSERVATION"
    RE_RESOLVE_ENTITY = "RE_RESOLVE_ENTITY"
    RE_RESOLVE_CAPABILITY = "RE_RESOLVE_CAPABILITY"
    SWITCH_PROVIDER = "SWITCH_PROVIDER"
    REPLAN_TASK = "REPLAN_TASK"
    REQUEST_USER_CONFIRMATION = "REQUEST_USER_CONFIRMATION"
    ABORT_SAFE = "ABORT_SAFE"

class Recovery(BaseModel):
    recovery_id: str = Field(description="Unique identifier for the recovery attempt.")
    strategy: RecoveryStrategy = Field(description="The bounded explicit recovery strategy to apply.")
    reason: str = Field(description="Why this recovery strategy was triggered.")
    attempts_remaining: int = Field(default=3, description="Bounded retry counter for this specific strategy.")

class Memory(BaseModel):
    memory_id: str = Field(description="Unique identifier for this memory context.")
    active_goal: Optional[Goal] = Field(default=None, description="The current active goal being pursued.")
    entity_references: Dict[str, Entity] = Field(default_factory=dict, description="Contextual entity tracking (e.g. for resolving 'it').")
    observation_history: List[Observation] = Field(default_factory=list, description="Historical record of past observations.")
    recovery_history: List[Recovery] = Field(default_factory=list, description="Historical record of recovery attempts.")
