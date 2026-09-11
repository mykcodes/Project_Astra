import pytest
import math
from unittest.mock import patch, MagicMock
from app.domain.entities import ScreenPoint, TriState
from app.interaction.input.mouse_controller import MouseController

@pytest.fixture
def mock_mouse_controller():
    # Create instance without real ctypes dependencies
    with patch("ctypes.windll.user32", create=True) as mock_user32:
        controller = MouseController()
        controller.user32 = mock_user32
        
        # Setup metrics for multi-monitor setup (e.g. left monitor is negative)
        # SM_XVIRTUALSCREEN = 76, SM_YVIRTUALSCREEN = 77, SM_CXVIRTUALSCREEN = 78, SM_CYVIRTUALSCREEN = 79
        def get_metrics(metric_id):
            if metric_id == 76: return -1920
            if metric_id == 77: return -1080
            if metric_id == 78: return 3840 # Total width
            if metric_id == 79: return 2160 # Total height
            return 0
        mock_user32.GetSystemMetrics.side_effect = get_metrics
        
        # Mock SendInput to always succeed (return number of inputs)
        mock_user32.SendInput.side_effect = lambda n, p, s: n
        
        return controller

def test_is_valid_coordinate(mock_mouse_controller):
    # Valid positive
    assert mock_mouse_controller._is_valid_coordinate(ScreenPoint(x=100, y=100)) is True
    # Valid negative (within bounds)
    assert mock_mouse_controller._is_valid_coordinate(ScreenPoint(x=-1000, y=-500)) is True
    
    # Out of bounds
    assert mock_mouse_controller._is_valid_coordinate(ScreenPoint(x=-2000, y=0)) is False
    assert mock_mouse_controller._is_valid_coordinate(ScreenPoint(x=0, y=2000)) is False
    assert mock_mouse_controller._is_valid_coordinate(ScreenPoint(x=2000, y=0)) is False

def test_actuate_move_success(mock_mouse_controller):
    result = mock_mouse_controller.actuate_move(ScreenPoint(x=100, y=100))
    assert result["success"] is True
    assert result["action"] == "MOVE_MOUSE"
    assert result["verified"] == TriState.TRUE

def test_actuate_move_out_of_bounds(mock_mouse_controller):
    result = mock_mouse_controller.actuate_move(ScreenPoint(x=-9999, y=-9999))
    assert result["success"] is False
    assert result["error"]["code"] == "OUT_OF_BOUNDS"

def test_actuate_click_success(mock_mouse_controller):
    result = mock_mouse_controller.actuate_click(ScreenPoint(x=100, y=100))
    assert result["success"] is True
    assert result["action"] == "CLICK"
    assert result["verified"] == TriState.UNKNOWN

def test_actuate_double_click_success(mock_mouse_controller):
    result = mock_mouse_controller.actuate_double_click(ScreenPoint(x=100, y=100))
    assert result["success"] is True
    assert result["action"] == "DOUBLE_CLICK"
    assert result["verified"] == TriState.UNKNOWN
