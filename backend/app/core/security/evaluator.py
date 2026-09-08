import uuid
from typing import Dict, List, Optional
from datetime import datetime, timezone, timedelta
from app.domain.permissions import (
    PermissionState, CapabilityScope, ResourceScope, 
    PermissionGrant, PermissionRequest, AuthorizationDecision
)

class PermissionEvaluator:
    """Evaluates permission requests against the current grant store."""
    
    def __init__(self):
        self._grants: Dict[str, PermissionGrant] = {}
        
    def evaluate(self, request: PermissionRequest) -> AuthorizationDecision:
        decision = self.is_authorized(request)
        return decision

    def grant(self, request: PermissionRequest, reason: str,
              duration_seconds: Optional[int] = None,
              constraints: Optional[Dict] = None) -> PermissionGrant:
        
        now = datetime.now(timezone.utc)
        expires_at = None
        if duration_seconds:
            expires_at = now + timedelta(seconds=duration_seconds)
            
        grant = PermissionGrant(
            grant_id=str(uuid.uuid4()),
            capability=request.capability,
            resource_scope=request.resource_scope,
            state=PermissionState.GRANTED,
            requester_task_id=request.requester_task_id,
            requester_context=request.requester_context,
            reason=reason,
            origin="Evaluator.grant",
            granted_at=now,
            expires_at=expires_at,
            duration_seconds=duration_seconds,
            constraints=constraints or {}
        )
        self._grants[grant.grant_id] = grant
        return grant

    def revoke(self, grant_id: str, reason: str) -> bool:
        if grant_id in self._grants:
            grant = self._grants[grant_id]
            grant.state = PermissionState.REVOKED
            grant.revoked_at = datetime.now(timezone.utc)
            grant.revocation_reason = reason
            return True
        return False

    def get_grants_for_task(self, task_id: str) -> List[PermissionGrant]:
        return [g for g in self._grants.values() if g.requester_task_id == task_id]

    def get_grants_for_capability(self, capability: CapabilityScope) -> List[PermissionGrant]:
        return [g for g in self._grants.values() if g.capability == capability]

    def is_authorized(self, request: PermissionRequest) -> AuthorizationDecision:
        now = datetime.now(timezone.utc)
        
        # Check active grants first
        for grant in self._grants.values():
            if grant.capability == request.capability and grant.state == PermissionState.GRANTED:
                # Check expiration
                if grant.expires_at and now > grant.expires_at:
                    grant.state = PermissionState.EXPIRED
                    continue
                    
                # Match resource if provided
                if grant.resource_scope.resource == request.resource_scope.resource or grant.resource_scope.resource is None:
                    # Match task ID if required
                    if grant.requester_task_id == request.requester_task_id or grant.requester_task_id is None:
                        return AuthorizationDecision(
                            request=request,
                            decision=PermissionState.GRANTED,
                            grant=grant,
                            reason=f"Matched active grant {grant.grant_id}"
                        )

        # Default Policies for Phase A
        if request.capability == CapabilityScope.SYSTEM_INFORMATION:
            return AuthorizationDecision(
                request=request, decision=PermissionState.NOT_REQUIRED,
                reason="Read-only system queries do not require permission"
            )
            
        # APPLICATION_LIFECYCLE and BROWSER_CONTROL are scoped per user command
        # If we got here, there's no active grant. It requires user command authority.
        # In a real flow, the command executor would grant this before executing.
        if request.capability in [CapabilityScope.APPLICATION_LIFECYCLE, CapabilityScope.BROWSER_CONTROL]:
            return AuthorizationDecision(
                request=request, decision=PermissionState.REQUIRED,
                reason="Requires user command authority"
            )

        # Everything else requires explicit authorization
        return AuthorizationDecision(
            request=request, decision=PermissionState.REQUIRED,
            reason="Explicit authorization required"
        )

# Global instance for Phase A
permission_evaluator = PermissionEvaluator()
