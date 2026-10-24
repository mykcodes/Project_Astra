"""
ASTRA Domain Checkpoint Contracts (Phase B.9)

Defines explicit, versioned checkpoint models for long-running goals and tasks.
Supports reliable serialization, environmental re-verification, and safe resumption.
Guarantees separation between attempted actuation, verified success, and persistent state.
"""

from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field, field_validator

from app.domain.entities import TriState
from app.domain.goals import Goal, Task, GoalState, TaskState, FailureClass, VerificationResult
from app.domain.composite import StepStatus, CompositeStep
from app.domain.clarification import ClarificationRequest


SCHEMA_VERSION: str = "1.0"


class ResumptionClassification(str, Enum):
    """Classification of step/task safety when evaluating checkpoint continuation."""
    VERIFIED_AND_SAFE = "VERIFIED_AND_SAFE"        # Step outcome verified; retain without repeating
    REQUIRES_REVERIFICATION = "REQUIRES_REVERIFICATION"  # Outcome uncertain; verify fresh state before proceeding
    SAFE_TO_RETRY = "SAFE_TO_RETRY"                # Idempotent action; safe to execute
    REQUIRES_REPLANNING = "REQUIRES_REPLANNING"    # Environment drifted; remainder sequence needs replan
    REQUIRES_USER_INTERVENTION = "REQUIRES_USER_INTERVENTION" # Non-idempotent or ambiguous; requires human approval
    UNSAFE_TO_RESUME = "UNSAFE_TO_RESUME"          # Terminal, corrupted, or unrecoverable state


class TaskCheckpoint(BaseModel):
    """
    Durable snapshot of an individual task within a goal.
    Persists verifiable evidence and step progress without live OS handles.
    """
    task_id: str = Field(description="Unique identifier for the task.")
    task_index: int = Field(default=0, description="0-indexed order of task in the goal.")
    description: str = Field(description="Human-readable description of the task.")
    task_state: TaskState = Field(default=TaskState.PLANNING, description="Current lifecycle state of the task.")
    target_app_name: Optional[str] = Field(default=None, description="Target application name (e.g. 'notepad').")
    target_application: Optional[str] = Field(default=None, description="Alternative target app name alias.")
    target_window_pattern: Optional[str] = Field(default=None, description="Window title pattern or class targeted.")
    
    # Progress and verification tracking
    step_indices: List[int] = Field(
        default_factory=list,
        description="List of step indices belonging to this task."
    )
    completed_step_indices: List[int] = Field(
        default_factory=list,
        description="Indices of steps whose actuation was accepted by the OS."
    )
    last_completed_step: Optional[int] = Field(
        default=None,
        description="Last step index whose actuation was accepted."
    )
    verified_step_indices: List[int] = Field(
        default_factory=list,
        description="Indices of steps whose outcome was authoritatively verified (TriState.TRUE)."
    )
    last_verified_step: Optional[int] = Field(
        default=None,
        description="Last step index whose outcome was authoritatively verified."
    )
    step_statuses: Dict[int, StepStatus] = Field(
        default_factory=dict,
        description="Step lifecycle status keyed by step index."
    )
    step_verifications: Dict[int, VerificationResult] = Field(
        default_factory=dict,
        description="Authoritative verification results keyed by step index."
    )
    verified_evidence: Dict[str, Any] = Field(
        default_factory=dict,
        description="Persisted verification evidence dictionary."
    )
    
    is_verified: bool = Field(default=False, description="Whether the overall task outcome was verified.")
    is_terminal: bool = Field(default=False, description="Whether this task is in a terminal state.")
    retry_count: int = Field(default=0, description="Number of recovery retries attempted for this task.")
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this task checkpoint was last modified."
    )

    @field_validator("task_state", mode="before")
    def parse_task_state(cls, v):
        if isinstance(v, str):
            try:
                return TaskState(v)
            except ValueError:
                return TaskState.PLANNING
        return v

    @field_validator("updated_at", mode="before")
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskCheckpoint":
        # Synchronize field aliases if present
        if "state" in data and "task_state" not in data:
            data["task_state"] = data["state"]
        if "target_application" in data and "target_app_name" not in data:
            data["target_app_name"] = data["target_application"]
        return cls.model_validate(data)


class GoalCheckpoint(BaseModel):
    """
    Durable snapshot of a multi-stage Goal.
    Captures complete execution state, task checkpoints, and environment context.
    Strictly avoids persisting live OS handles, HWNDs, or provider connections.
    """
    checkpoint_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this checkpoint record."
    )
    schema_version: str = Field(default=SCHEMA_VERSION, description="Schema version of this checkpoint.")
    goal_id: str = Field(description="Identifier of the goal being tracked.")
    objective: str = Field(default="", description="The overarching user objective.")
    goal_state: GoalState = Field(default=GoalState.PLAN_CREATED, description="Current state of the goal.")
    
    # Execution position
    current_task_index: int = Field(default=0, description="Index of the currently active task.")
    total_tasks: int = Field(default=0, description="Total number of tasks planned for this goal.")
    completed_tasks: List[str] = Field(
        default_factory=list,
        description="List of task IDs that completed and verified successfully."
    )
    verified_steps: Dict[str, List[int]] = Field(
        default_factory=dict,
        description="Mapping of task_id to list of verified step indices."
    )
    task_checkpoints: List[TaskCheckpoint] = Field(
        default_factory=list,
        description="Snapshots of all tasks associated with this goal."
    )
    
    # Contextual provenance
    execution_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Execution session identifier."
    )
    environment_snapshot: Dict[str, Any] = Field(
        default_factory=dict,
        description="Environment context snapshot (window names, URL, timestamps)."
    )
    recovery_history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Recovery and replanning audit history."
    )
    
    # Suspension and resumption metadata
    suspension_reason: Optional[str] = Field(
        default=None,
        description="Reason for suspension if in WAITING_FOR_USER or paused state."
    )
    pending_clarification: Optional[ClarificationRequest] = Field(
        default=None,
        description="Pending clarification or confirmation request if state is WAITING_FOR_USER."
    )
    is_resumable: bool = Field(
        default=True,
        description="Whether this goal is eligible for automatic or user-approved resumption."
    )
    failure_class: Optional[FailureClass] = Field(
        default=None,
        description="Failure classification if goal failed."
    )
    goal_payload: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Serialized representation of the Goal domain model."
    )
    
    # Timestamps
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when the goal execution was first checkpointed."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this checkpoint was last updated."
    )

    @field_validator("goal_state", mode="before")
    def parse_goal_state(cls, v):
        if isinstance(v, str):
            try:
                return GoalState(v)
            except ValueError:
                return GoalState.PLANNING
        return v

    @field_validator("created_at", "updated_at", mode="before")
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    def to_dict(self) -> Dict[str, Any]:
        """Converts model to JSON-safe dictionary."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GoalCheckpoint":
        """Reconstructs GoalCheckpoint from dictionary."""
        return cls.model_validate(data)

    def to_json(self) -> str:
        """Serializes model to JSON string."""
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "GoalCheckpoint":
        """Reconstructs GoalCheckpoint from JSON string."""
        return cls.model_validate_json(json_str)

    def validate_resumable(self) -> tuple[bool, str]:
        """
        Validates whether this checkpoint satisfies all safety invariants for resumption.
        Returns (is_valid, reason).
        """
        if self.schema_version != SCHEMA_VERSION:
            return False, f"Incompatible schema version: {self.schema_version} (expected {SCHEMA_VERSION})"
        
        if self.goal_state in (GoalState.COMPLETED, GoalState.CANCELLED):
            return False, f"Goal is in terminal state ({self.goal_state.value}); cannot be reopened."
            
        if not self.is_resumable:
            return False, "Checkpoint is marked non-resumable."
            
        if self.current_task_index < 0 or (self.total_tasks > 0 and self.current_task_index >= self.total_tasks):
            return False, f"Invalid current task index: {self.current_task_index} for {self.total_tasks} tasks."
            
        return True, "Checkpoint is valid and eligible for resumption."
