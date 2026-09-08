import pytest
from app.domain.permissions import (
    PermissionState, CapabilityScope, ResourceScope, PermissionRequest
)
from app.core.security.evaluator import PermissionEvaluator

def test_permission_evaluator_default_policies():
    evaluator = PermissionEvaluator()
    
    # SYSTEM_INFORMATION -> NOT_REQUIRED
    req1 = PermissionRequest(
        request_id="req1", capability=CapabilityScope.SYSTEM_INFORMATION,
        resource_scope=ResourceScope(capability=CapabilityScope.SYSTEM_INFORMATION),
        reason="Test"
    )
    dec1 = evaluator.evaluate(req1)
    assert dec1.decision == PermissionState.NOT_REQUIRED
    
    # APPLICATION_LIFECYCLE -> REQUIRED
    req2 = PermissionRequest(
        request_id="req2", capability=CapabilityScope.APPLICATION_LIFECYCLE,
        resource_scope=ResourceScope(capability=CapabilityScope.APPLICATION_LIFECYCLE, resource="chrome"),
        reason="Test"
    )
    dec2 = evaluator.evaluate(req2)
    assert dec2.decision == PermissionState.REQUIRED
    
    # FILE_ACCESS -> REQUIRED
    req3 = PermissionRequest(
        request_id="req3", capability=CapabilityScope.FILE_ACCESS,
        resource_scope=ResourceScope(capability=CapabilityScope.FILE_ACCESS),
        reason="Test"
    )
    dec3 = evaluator.evaluate(req3)
    assert dec3.decision == PermissionState.REQUIRED

def test_permission_grant_lifecycle():
    evaluator = PermissionEvaluator()
    
    req = PermissionRequest(
        request_id="req_test", capability=CapabilityScope.APPLICATION_LIFECYCLE,
        resource_scope=ResourceScope(capability=CapabilityScope.APPLICATION_LIFECYCLE, resource="notepad"),
        reason="User requested opening notepad",
        requester_task_id="task_1"
    )
    
    # Initially REQUIRED
    assert evaluator.evaluate(req).decision == PermissionState.REQUIRED
    
    # Grant
    grant = evaluator.grant(req, reason="Command executed")
    assert grant.state == PermissionState.GRANTED
    assert grant.capability == CapabilityScope.APPLICATION_LIFECYCLE
    
    # Now it should be GRANTED
    dec2 = evaluator.evaluate(req)
    assert dec2.decision == PermissionState.GRANTED
    assert dec2.grant.grant_id == grant.grant_id
    
    # Revoke
    assert evaluator.revoke(grant.grant_id, reason="Task completed")
    
    # Now it should be REQUIRED again
    dec3 = evaluator.evaluate(req)
    assert dec3.decision == PermissionState.REQUIRED
