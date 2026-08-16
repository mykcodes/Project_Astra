from enum import Enum
from typing import Any, Dict, List, Optional
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

class WorldState(BaseModel):
    timestamp: str = Field(description="ISO 8601 timestamp of this state snapshot.")
    observed_state: List[Entity] = Field(default_factory=list, description="Verifiable data directly observed from the environment.")
    inferred_state: List[Entity] = Field(default_factory=list, description="Entities inferred from history or LLM reasoning.")
    context: Dict[str, Any] = Field(default_factory=dict, description="Global environmental context variables.")

class Observation(BaseModel):
    observation_id: str = Field(description="Unique identifier for this observation.")
    world_state: WorldState = Field(description="The snapshot of the world resulting from this observation.")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Raw evidence collected (e.g., screenshot paths, API responses).")
