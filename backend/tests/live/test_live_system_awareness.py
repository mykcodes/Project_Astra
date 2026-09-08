import pytest
import os
import time
from app.environment.awareness.windows import WindowsSystemAwarenessProvider
from app.domain.entities import TriState, ObservationStatus

@pytest.fixture
def provider():
    return WindowsSystemAwarenessProvider()

@pytest.mark.live
def test_detect_known_running_application(provider):
    # The python process running pytest should be detectable if we know its name.
    app = provider.observe_application("python")
    assert app.running == TriState.TRUE
    assert len(app.process_ids) > 0

@pytest.mark.live
def test_detect_not_running_application(provider):
    # Fabricated name
    app = provider.observe_application("non_existent_fake_app_12345")
    assert app.running == TriState.FALSE
    assert len(app.process_ids) == 0

@pytest.mark.live
def test_detect_foreground_application(provider):
    fg = provider.observe_foreground()
    if fg is not None:
        assert fg.handle > 0
        # Process name should be populated if it has a valid PID
        assert fg.owner_application != ""

@pytest.mark.live
def test_window_properties(provider):
    # Find any visible window to test properties
    windows = provider.observe_windows()
    visible_windows = [w for w in windows if w.visible == TriState.TRUE]
    
    if visible_windows:
        w = visible_windows[0]
        assert w.handle > 0
        # Title can be empty string, but must be string
        assert isinstance(w.title, str)
        # owner_application should be populated
        assert w.owner_application != ""
        # Minimized / Maximized must be TriState
        assert isinstance(w.minimized, TriState)
        assert isinstance(w.maximized, TriState)
        # Bounds should exist if visible and not minimized, though sometimes x/y can be weird, let's just check type
        if w.bounds:
            assert w.bounds.width > 0
            assert w.bounds.height > 0

@pytest.mark.live
def test_world_state_overall(provider):
    ws = provider.observe_world_state()
    assert ws.observation.status == ObservationStatus.SUCCESS
    assert ws.system.os_name == "Windows"
    assert len(ws.applications) >= 0
    
    if len(ws.applications) > 0:
        # If we have apps, make sure process info exists
        for app in ws.applications:
            assert len(app.process_ids) > 0
            assert app.identity.canonical_name != ""
            
    assert len(ws.windows) >= 0
    assert ws.observation.timestamp is not None
