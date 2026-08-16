from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class Permission(BaseModel):
    permission_id: str = Field(description="Unique identifier for the permission (e.g., 'filesystem:write').")
    description: str = Field(description="Human-readable description of what this permission grants.")
    is_granted: bool = Field(default=False, description="Whether the permission is currently granted.")

class Capability(BaseModel):
    capability_id: str = Field(description="Unique identifier for the abstract capability (e.g., 'navigate_browser').")
    name: str = Field(description="Human-readable name of the capability.")
    description: str = Field(description="Detailed description of what the capability accomplishes.")
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema defining expected input parameters.")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="JSON schema defining the expected output.")
    required_permissions: List[Permission] = Field(default_factory=list, description="Permissions required to execute this capability.")
    supported_providers: List[str] = Field(default_factory=list, description="List of provider IDs capable of fulfilling this capability.")
    risk_level: str = Field(description="Risk classification (e.g., 'low', 'medium', 'high', 'critical').")

class Provider(BaseModel):
    provider_id: str = Field(description="Unique identifier for the provider implementation (e.g., 'playwright', 'uiautomation').")
    capabilities: List[str] = Field(default_factory=list, description="List of capability IDs this provider can fulfill.")
    availability: str = Field(description="Current availability status of the provider (e.g., 'available', 'unavailable').")
    constraints: Dict[str, Any] = Field(default_factory=dict, description="Environment constraints or limits for this provider.")
    priority: int = Field(default=0, description="Selection priority. Higher number means higher preference.")
    security_requirements: List[str] = Field(default_factory=list, description="Security boundaries required for execution.")
