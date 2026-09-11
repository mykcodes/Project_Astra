from enum import Enum
from typing import Any, Dict, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class EntityType(str, Enum):
    APPLICATION = "Application"
    WEBSITE = "Website"
    FILE = "File"
    FOLDER = "Folder"
    DOCUMENT = "Document"
    PROCESS = "Process"
    WINDOW = "Window"
    BROWSER = "Browser"
    BROWSERTAB = "BrowserTab"
    DEVICE = "Device"
    PERSON = "Person"
    SERVICE = "Service"
    UIELEMENT = "UIElement"
    GENERIC = "Generic"

class Entity(BaseModel):
    id: str = Field(description="Unique identifier for the entity within the world state.")
    entity_type: EntityType = Field(description="The formal category of the entity.")
    name: str = Field(description="Human-readable name or title of the entity.")
    properties: Dict[str, Any] = Field(default_factory=dict, description="Semantic properties specific to the entity type.")

class ScreenPoint(BaseModel):
    x: int
    y: int

class TriState(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"

class ObservationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"

class FreshnessState(str, Enum):
    FRESH = "FRESH"
    STALE = "STALE"
    INVALID = "INVALID"
    UNKNOWN = "UNKNOWN"

class SystemInfo(BaseModel):
    os_name: str
    os_version: str
    machine_name: str
    timestamp: str = Field(description="ISO 8601 timestamp of when system info was observed")

class ApplicationIdentity(BaseModel):
    canonical_name: str
    display_name: str
    executable: Optional[str] = None
    process_names: List[str] = Field(default_factory=list)
    application_type: str = "UNKNOWN"

class ApplicationInfo(BaseModel):
    identity: ApplicationIdentity
    running: TriState
    process_ids: List[int] = Field(default_factory=list)
    window_count: int = 0
    window_handles: List[int] = Field(default_factory=list)
    responsive: TriState = TriState.UNKNOWN

class WindowBounds(BaseModel):
    x: int
    y: int
    width: int
    height: int

class WindowInfo(BaseModel):
    handle: int
    owner_application: str
    owner_pid: int
    title: str
    process_name: Optional[str] = None
    visible: TriState
    foreground: TriState
    minimized: TriState
    maximized: TriState
    bounds: Optional[WindowBounds] = None
    responsive: TriState = TriState.UNKNOWN

class ForegroundInfo(BaseModel):
    handle: int
    owner_application: str
    title: str
    process_name: Optional[str] = None

class ObservationMetadata(BaseModel):
    timestamp: datetime = Field(description="When the observation was taken")
    source: str
    duration_ms: Optional[float] = None
    status: ObservationStatus
    error: Optional[str] = None

class WorldState(BaseModel):
    system: SystemInfo
    applications: List[ApplicationInfo] = Field(default_factory=list)
    windows: List[WindowInfo] = Field(default_factory=list)
    foreground: Optional[ForegroundInfo] = None
    observation: ObservationMetadata

class Observation(BaseModel):
    observation_id: str = Field(description="Unique identifier for this observation.")
    world_state: WorldState = Field(description="The snapshot of the world resulting from this observation.")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Raw evidence collected (e.g., VisualObservation metadata, API responses). Do NOT store large image blobs here.")
