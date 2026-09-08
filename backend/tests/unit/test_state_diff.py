import pytest
import os
from datetime import datetime, timezone
from app.domain.entities import (
    WorldState, ApplicationInfo, ApplicationIdentity, SystemInfo, ObservationMetadata, 
    ObservationStatus, TriState, WindowInfo, ForegroundInfo, WindowBounds
)
from app.environment.awareness.diff import compute_diff, WorldStateChangeType

def create_mock_world_state(apps, windows, fg=None):
    return WorldState(
        system=SystemInfo(os_name="Test", os_version="1", machine_name="Test", timestamp="2026-08-14T10:00:00Z"),
        applications=apps,
        windows=windows,
        foreground=fg,
        observation=ObservationMetadata(timestamp=datetime.now(timezone.utc), source="test", status=ObservationStatus.SUCCESS)
    )

def test_diff_application_opened_closed():
    app1 = ApplicationInfo(identity=ApplicationIdentity(canonical_name="app1", display_name="App 1"), running=TriState.TRUE)
    
    ws1 = create_mock_world_state([], [])
    ws2 = create_mock_world_state([app1], [])
    ws3 = create_mock_world_state([], [])
    
    # Diff 1 to 2 -> Opened
    diff1 = compute_diff(ws1, ws2)
    assert len(diff1.changes) == 1
    assert diff1.changes[0].change_type == WorldStateChangeType.APPLICATION_OPENED
    assert diff1.changes[0].entity_id == "app1"
    
    # Diff 2 to 3 -> Closed
    diff2 = compute_diff(ws2, ws3)
    assert len(diff2.changes) == 1
    assert diff2.changes[0].change_type == WorldStateChangeType.APPLICATION_CLOSED
    assert diff2.changes[0].entity_id == "app1"

def test_diff_window_and_title_changed():
    w1 = WindowInfo(handle=100, owner_application="app1", owner_pid=1, title="Test Window", visible=TriState.TRUE, foreground=TriState.FALSE, minimized=TriState.FALSE, maximized=TriState.FALSE)
    w2 = WindowInfo(handle=100, owner_application="app1", owner_pid=1, title="Test Window - Updated", visible=TriState.TRUE, foreground=TriState.FALSE, minimized=TriState.FALSE, maximized=TriState.FALSE)
    
    ws1 = create_mock_world_state([], [w1])
    ws2 = create_mock_world_state([], [w2])
    
    diff = compute_diff(ws1, ws2)
    assert len(diff.changes) == 1
    assert diff.changes[0].change_type == WorldStateChangeType.TITLE_CHANGED
    assert diff.changes[0].old_value == "Test Window"
    assert diff.changes[0].new_value == "Test Window - Updated"
    
def test_diff_foreground_changed():
    fg1 = ForegroundInfo(handle=100, owner_application="app1", title="Window 1")
    fg2 = ForegroundInfo(handle=200, owner_application="app2", title="Window 2")
    
    ws1 = create_mock_world_state([], [], fg=fg1)
    ws2 = create_mock_world_state([], [], fg=fg2)
    
    diff = compute_diff(ws1, ws2)
    assert len(diff.changes) == 1
    assert diff.changes[0].change_type == WorldStateChangeType.FOREGROUND_CHANGED
    assert diff.changes[0].old_value == "100"
    assert diff.changes[0].new_value == "200"
