import pytest
from datetime import datetime
from app.domain.entities import (
    TriState, ObservationStatus, FreshnessState,
    SystemInfo, ApplicationIdentity, ApplicationInfo,
    WindowBounds, WindowInfo, ForegroundInfo,
    ObservationMetadata, WorldState
)

def test_tristate_semantics():
    # TriState is strictly TRUE, FALSE, UNKNOWN.
    # UNKNOWN should never be implicitly cast to a boolean False if checked properly.
    assert TriState.UNKNOWN != TriState.FALSE
    assert TriState.UNKNOWN != TriState.TRUE
    assert TriState.TRUE != TriState.FALSE

def test_world_state_construction():
    sys_info = SystemInfo(
        os_name="Windows", os_version="10", machine_name="TEST-PC",
        timestamp="2026-08-14T10:00:00Z"
    )
    
    app_ident = ApplicationIdentity(
        canonical_name="chrome", display_name="Google Chrome"
    )
    
    app_info = ApplicationInfo(
        identity=app_ident, running=TriState.TRUE, process_ids=[1234]
    )
    
    win_info = WindowInfo(
        handle=9999, owner_application="chrome", owner_pid=1234,
        title="Google - Google Chrome", visible=TriState.TRUE,
        foreground=TriState.FALSE, minimized=TriState.FALSE,
        maximized=TriState.TRUE, bounds=WindowBounds(x=0, y=0, width=1920, height=1080),
        responsive=TriState.TRUE
    )
    
    obs_meta = ObservationMetadata(
        timestamp=datetime.now(), source="test", status=ObservationStatus.SUCCESS
    )
    
    ws = WorldState(
        system=sys_info, applications=[app_info], windows=[win_info], observation=obs_meta
    )
    
    # Verify Application vs Window separation
    assert not hasattr(app_info, 'minimized')
    assert hasattr(win_info, 'minimized')
    
    assert ws.applications[0].running == TriState.TRUE
    assert ws.windows[0].maximized == TriState.TRUE
