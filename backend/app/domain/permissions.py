from enum import Enum
from typing import Any, Dict, Optional
from datetime import datetime
from pydantic import BaseModel, Field

class PermissionState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"

class CapabilityScope(str, Enum):
    SYSTEM_INFORMATION = "SYSTEM_INFORMATION"
    COMPUTER_CONTROL = "COMPUTER_CONTROL"
    FILE_ACCESS = "FILE_ACCESS"
    BACKGROUND_EXECUTION = "BACKGROUND_EXECUTION"
    BROWSER_CONTROL = "BROWSER_CONTROL"
    NETWORK_ACCESS = "NETWORK_ACCESS"
    CREDENTIAL_ACCESS = "CREDENTIAL_ACCESS"
    SYSTEM_MODIFICATION = "SYSTEM_MODIFICATION"
    APPLICATION_LIFECYCLE = "APPLICATION_LIFECYCLE"

class ResourceScope(BaseModel):
    capability: CapabilityScope
    resource: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)

class PermissionGrant(BaseModel):
    grant_id: str
    capability: CapabilityScope
    resource_scope: ResourceScope
    state: PermissionState
    requester_task_id: Optional[str] = None
    requester_context: Optional[str] = None
    reason: str
    origin: str
    granted_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    duration_seconds: Optional[int] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    revoked_at: Optional[datetime] = None
    revocation_reason: Optional[str] = None

class PermissionRequest(BaseModel):
    request_id: str
    requester_task_id: Optional[str] = None
    requester_context: Optional[str] = None
    capability: CapabilityScope
    resource_scope: ResourceScope
    reason: str
    urgency: str = "normal"

class AuthorizationDecision(BaseModel):
    request: PermissionRequest
    decision: PermissionState
    grant: Optional[PermissionGrant] = None
    reason: str
    requires_user_approval: bool = False
