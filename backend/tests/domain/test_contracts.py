import pytest
import json
from app.domain.entities import Entity, EntityType, WorldState, Observation
from app.domain.capabilities import Permission, Capability, Provider
from app.domain.goals import Intent, Action, Task, TaskState, Goal
from app.domain.memory import Recovery, RecoveryStrategy, Memory

def test_entity_serialization():
    entity = Entity(id="1", entity_type=EntityType.WEBSITE, name="Amazon", properties={"url": "https://amazon.com"})
    data = entity.model_dump()
    assert data["entity_type"] == "Website"
    
    entity_str = entity.model_dump_json()
    assert "Website" in entity_str

def test_world_state_construction():
    from datetime import datetime
    from app.domain.entities import (
        SystemInfo, ApplicationIdentity, ApplicationInfo, TriState,
        ObservationMetadata, ObservationStatus
    )
    
    sys_info = SystemInfo(
        os_name="Windows", os_version="10", machine_name="TEST-PC",
        timestamp="2026-08-14T10:00:00Z"
    )
    
    app_ident = ApplicationIdentity(
        canonical_name="chrome", display_name="Google Chrome"
    )
    
    app_info = ApplicationInfo(
        identity=app_ident, running=TriState.TRUE
    )
    
    obs_meta = ObservationMetadata(
        timestamp=datetime.now(), source="test", status=ObservationStatus.SUCCESS
    )
    
    ws = WorldState(
        system=sys_info, applications=[app_info], observation=obs_meta
    )
    
    assert len(ws.applications) == 1
    assert ws.applications[0].identity.canonical_name == "chrome"
    assert ws.applications[0].running == TriState.TRUE

def test_capability_provider():
    perm = Permission(permission_id="fs:read", description="Read files", is_granted=True)
    cap = Capability(capability_id="read_file", name="Read File", description="Reads a file", risk_level="low", required_permissions=[perm])
    prov = Provider(provider_id="native_fs", capabilities=["read_file"], availability="available")
    assert cap.required_permissions[0].is_granted
    assert prov.capabilities == ["read_file"]

def test_task_state_transitions():
    task = Task(task_id="t1", description="Do work")
    assert task.state == TaskState.PLANNING
    task.state = TaskState.EXECUTING
    assert task.state == TaskState.EXECUTING

def test_recovery_strategy():
    rec = Recovery(recovery_id="r1", strategy=RecoveryStrategy.SWITCH_PROVIDER, reason="Provider timeout")
    assert rec.strategy == RecoveryStrategy.SWITCH_PROVIDER
    assert rec.attempts_remaining == 3
