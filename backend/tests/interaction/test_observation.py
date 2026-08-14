import pytest
from app.interaction.models import UIElement, UIElementState, UIObservation, UIChange
from app.interaction.ui.engine import ObservationEngine

def test_observation_diffing():
    engine = ObservationEngine()
    
    el1 = UIElement(runtime_id="el_1", name="Submit", control_type="Button", automation_id="btnSubmit", class_name="", framework_id="", process_id=0, window_handle=0)
    el2 = UIElement(runtime_id="el_1", name="Submit", control_type="Button", automation_id="btnSubmit", class_name="", framework_id="", process_id=0, window_handle=0)
    el2.state.focused = True
    
    obs1 = UIObservation(foreground_hwnd=100, elements={"el_1": el1})
    obs2 = UIObservation(foreground_hwnd=100, elements={"el_1": el2})
    
    # Need mock window
    from app.interaction.models import UIWindow
    w = UIWindow(hwnd=100, process_id=1, application_identity="test", framework="win32", title="test", role="", bounds=None, monitor=0, z_order=0, is_main_window=True, is_modal=False, is_popup=False, is_minimized=False, is_maximized=False, is_foreground=True)
    obs1.window = w
    obs2.window = w
    
    changes = engine.compare_state(obs1, obs2)
    assert len(changes) == 1
    assert changes[0].change_type == "FOCUS_GAINED"

# More tests to follow...
