"""
ASTRA Domain Memory & Knowledge Contracts (Phase B.10)

Defines versioned models for persistent cross-session memory, user facts/preferences,
application profiles, episodic goal summaries, and semantic intent grounding.
Strictly separates durable semantic knowledge from ephemeral OS handles.
"""

from datetime import datetime, timezone
from enum import Enum
import uuid
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from app.domain.entities import Entity, Observation
from app.domain.goals import Goal, Task


MEMORY_SCHEMA_VERSION: str = "1.0"


class MemoryType(str, Enum):
    """Categorical taxonomy for ASTRA memory subsystems."""
    SHORT_TERM = "short_term"   # Active prompt window / turn context
    WORKING = "working"         # Active project / execution state
    LONG_TERM = "long_term"     # Explicitly stored user facts & durable preferences
    EPISODIC = "episodic"       # Verified summaries of past completed goal runs
    SEMANTIC = "semantic"       # Concepts, application profiles & entity alias mappings
    FACT = "fact"               # Explicit user facts (e.g. work location, hardware setup)
    PREFERENCE = "preference"   # Explicit user preferences (e.g. default browser, editor)


class ProvenanceType(str, Enum):
    """Source and confidence provenance for remembered information."""
    USER_EXPLICIT = "USER_EXPLICIT"             # Stated explicitly by the user
    USER_PREFERENCE = "USER_PREFERENCE"         # User preference for an app, tool, or workflow
    APPLICATION_PROFILE = "APPLICATION_PROFILE" # Installed application metadata and aliases
    EPISODIC_SUMMARY = "EPISODIC_SUMMARY"       # Automatically generated from verified goal run
    INFERRED = "INFERRED"                       # Inferred from repeated interaction patterns


class MemoryRecord(BaseModel):
    """
    A single durable memory record surviving across sessions.
    Maintains provenance, categorical tags, access audit metrics,
    and guarantees no ephemeral OS handles are persisted.
    """
    memory_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique identifier for this memory record."
    )
    schema_version: str = Field(
        default=MEMORY_SCHEMA_VERSION,
        description="Contract schema version for forward/backward compatibility."
    )
    version: int = Field(
        default=1,
        ge=1,
        description="Revision number of this memory record, incremented upon updates."
    )
    memory_type: MemoryType = Field(
        default=MemoryType.LONG_TERM,
        description="Taxonomical memory type."
    )
    key: str = Field(
        description="Unique lookup key or semantic slug (e.g., 'pref:browser', 'user:work_dir')."
    )
    content: str = Field(
        description="Natural language statement or structured text describing the memory."
    )
    tags: List[str] = Field(
        default_factory=list,
        description="Categorical search tags for indexing and fast filtering."
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Structured key-value payload (strictly devoid of live OS handles)."
    )
    provenance: ProvenanceType = Field(
        default=ProvenanceType.USER_EXPLICIT,
        description="Origin and trustworthiness category of this memory."
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Confidence score in the veracity of this memory."
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this memory was created."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this memory was last updated."
    )
    access_count: int = Field(
        default=0,
        ge=0,
        description="Number of times this memory was retrieved and applied."
    )
    last_accessed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp of the most recent retrieval."
    )

    @field_validator("created_at", "updated_at", "last_accessed_at", mode="before")
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    @field_validator("metadata")
    def sanitize_metadata(cls, v):
        """Invariant: Strictly strip live OS handles or ephemeral session IDs from memory."""
        forbidden_keys = {"target_hwnd", "hwnd", "pid", "thread_id", "browser_session_id", "active_page_id"}
        if isinstance(v, dict):
            return {k: val for k, val in v.items() if k.lower() not in forbidden_keys}
        return v

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryRecord":
        return cls.model_validate(data)

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, json_str: str) -> "MemoryRecord":
        return cls.model_validate_json(json_str)


class ApplicationProfile(BaseModel):
    """
    Semantic profile for an application, capturing natural-language aliases,
    category preferences, and execution parameters across sessions.
    """
    canonical_name: str = Field(
        description="Authoritative process/catalog name (e.g. 'notepad', 'brave', 'code')."
    )
    app_name: str = Field(
        default="",
        description="Human-readable application display name (e.g. 'Brave Browser')."
    )
    category: str = Field(
        default="application",
        description="Functional category (e.g. 'browser', 'editor', 'terminal', 'calc')."
    )
    aliases: List[str] = Field(
        default_factory=list,
        description="Natural language aliases or trigger phrases (e.g. ['my browser', 'web browser', 'brave'])."
    )
    is_preferred: bool = Field(
        default=False,
        description="Whether this application is the default preference for its category."
    )
    default_arguments: Dict[str, Any] = Field(
        default_factory=dict,
        description="Default intent parameters or CLI flags."
    )
    notes: str = Field(
        default="",
        description="Contextual user notes or environment constraints."
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when profile was last refreshed."
    )

    @model_validator(mode="before")
    def resolve_profile_fields(cls, values):
        if isinstance(values, dict):
            if "display_name" in values and ("app_name" not in values or not values["app_name"]):
                values["app_name"] = values["display_name"]
            elif "app_name" not in values or not values["app_name"]:
                values["app_name"] = values.get("canonical_name", "").title()
            if "is_default_for_category" in values and "is_preferred" not in values:
                values["is_preferred"] = values["is_default_for_category"]
        return values

    @property
    def display_name(self) -> str:
        return self.app_name or self.canonical_name.title()

    @property
    def is_default_for_category(self) -> bool:
        return self.is_preferred

    @field_validator("updated_at", mode="before")
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    def to_dict(self) -> Dict[str, Any]:
        d = self.model_dump(mode="json")
        d["display_name"] = self.display_name
        d["is_default_for_category"] = self.is_default_for_category
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApplicationProfile":
        return cls.model_validate(data)


class EpisodicGoalSummary(BaseModel):
    """
    A verified episodic record of a successfully completed goal run.
    Records objective, verified outcomes, and touched applications truthfully.
    """
    goal_id: str = Field(description="Identifier of the completed goal.")
    objective: str = Field(description="User objective pursued.")
    completed_tasks: List[str] = Field(
        default_factory=list,
        description="Descriptions of completed tasks."
    )
    verified_outcomes: List[str] = Field(
        default_factory=list,
        description="Explicit verifiable outcomes confirmed by the verification engine."
    )
    touched_applications: List[str] = Field(
        default_factory=list,
        description="Canonical names of applications manipulated."
    )
    summary_text: str = Field(
        default="",
        description="Concise natural-language summary of what was accomplished."
    )
    unverified_actions: List[str] = Field(
        default_factory=list,
        description="Actions performed without explicit verified outcome."
    )
    total_tasks: int = Field(
        default=0,
        description="Total tasks in the goal."
    )
    successful_tasks: int = Field(
        default=0,
        description="Number of completed tasks."
    )
    duration_seconds: float = Field(
        default=0.0,
        description="Execution duration in seconds."
    )
    completed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Completion timestamp."
    )

    @model_validator(mode="before")
    def resolve_episodic_fields(cls, values):
        if isinstance(values, dict):
            if "applications_involved" in values and "touched_applications" not in values:
                values["touched_applications"] = values["applications_involved"]
            if "summary_text" not in values or not values["summary_text"]:
                values["summary_text"] = values.get("objective", "")
        return values

    @property
    def applications_involved(self) -> List[str]:
        return self.touched_applications

    @field_validator("completed_at", mode="before")
    def parse_datetime(cls, v):
        if isinstance(v, str):
            return datetime.fromisoformat(v)
        return v

    def to_dict(self) -> Dict[str, Any]:
        d = self.model_dump(mode="json")
        d["applications_involved"] = self.touched_applications
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EpisodicGoalSummary":
        return cls.model_validate(data)


class MemoryQuery(BaseModel):
    """Query parameters for retrieving relevant cross-session memory items."""
    query_text: str = Field(default="", description="Natural language query string or keyword list.")
    memory_types: Optional[List[MemoryType]] = Field(
        default=None,
        description="Optional filter for specific memory types."
    )
    tags: Optional[List[str]] = Field(
        default=None,
        description="Optional filter for categorical tags."
    )
    limit: int = Field(default=5, ge=1, le=50, description="Maximum number of items to return.")
    min_score: float = Field(default=0.0, ge=0.0, description="Minimum relevance threshold.")

    @model_validator(mode="before")
    def resolve_query_field(cls, values):
        if isinstance(values, dict):
            if "query" in values and ("query_text" not in values or not values["query_text"]):
                values["query_text"] = values["query"]
        return values

    @property
    def query(self) -> str:
        return self.query_text


class MemorySearchResult(BaseModel):
    """A scored memory item returned from search ranking."""
    record: MemoryRecord
    score: float = Field(description="Relevance score (higher is more relevant).")
    matched_tokens: List[str] = Field(default_factory=list, description="Keywords that matched.")

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump(mode="json")


# ============================================================================
# Existing Models (Preserved for Backward Compatibility)
# ============================================================================

class RecoveryStrategy(str, Enum):
    REFRESH_OBSERVATION = "REFRESH_OBSERVATION"
    RE_RESOLVE_ENTITY = "RE_RESOLVE_ENTITY"
    RE_RESOLVE_CAPABILITY = "RE_RESOLVE_CAPABILITY"
    SWITCH_PROVIDER = "SWITCH_PROVIDER"
    REPLAN_TASK = "REPLAN_TASK"
    REQUEST_USER_CONFIRMATION = "REQUEST_USER_CONFIRMATION"
    ABORT_SAFE = "ABORT_SAFE"
    REBUILD_TARGET = "REBUILD_TARGET"
    WAIT_FOR_USER = "WAIT_FOR_USER"
    INSPECT_NAVIGATION = "INSPECT_NAVIGATION"
    INSPECT_STATE = "INSPECT_STATE"
    RECOVER_SESSION = "RECOVER_SESSION"
    ALTERNATE_TARGET = "ALTERNATE_TARGET"
    DETERMINE_RELEVANCE = "DETERMINE_RELEVANCE"


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
