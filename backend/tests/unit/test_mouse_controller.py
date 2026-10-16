import pytest
import math
import ctypes
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


@pytest.fixture
def single_monitor_mouse_controller():
    # Standard 1920x1080 single monitor
    with patch("ctypes.windll.user32", create=True) as mock_user32:
        controller = MouseController()
        controller.user32 = mock_user32
        
        def get_metrics(metric_id):
            if metric_id == 76: return 0
            if metric_id == 77: return 0
            if metric_id == 78: return 1920
            if metric_id == 79: return 1080
            return 0
        mock_user32.GetSystemMetrics.side_effect = get_metrics
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


def test_actuate_move_success_decoupled_from_verification(mock_mouse_controller):
    """By default (verify=False), actuate_move returns UNKNOWN because no observation was performed."""
    result = mock_mouse_controller.actuate_move(ScreenPoint(x=100, y=100))
    assert result["success"] is True
    assert result["action"] == "MOVE_MOUSE"
    assert result["actuation_status"] == "ACTUATION_ACCEPTED"
    assert result["verified"] == TriState.UNKNOWN


def test_actuate_move_out_of_bounds(mock_mouse_controller):
    result = mock_mouse_controller.actuate_move(ScreenPoint(x=-9999, y=-9999))
    assert result["success"] is False
    assert result["error"]["code"] == "OUT_OF_BOUNDS"
    assert result["verified"] == TriState.FALSE


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


# ── B.3.6 Coordinate Normalization Accuracy Tests ──

def test_normalize_coordinates_math_exact_reconstruction(single_monitor_mouse_controller):
    """
    Tests the 3 previously failing coordinates on 1920x1080 display:
    (500, 400), (759, 721), (960, 540).
    Reconstructed pixel via Windows bit-shift ((norm * dim) >> 16) must match exactly with 0 error.
    """
    failing_coords = [
        (500, 400),
        (759, 721),
        (960, 540),
    ]
    w, h = 1920, 1080
    for px, py in failing_coords:
        nx, ny = single_monitor_mouse_controller._normalize_coordinates(ScreenPoint(x=px, y=py))
        
        # Windows win32k fixed-point reconstruction
        recon_x = (nx * w) >> 16
        recon_y = (ny * h) >> 16
        
        assert recon_x == px, f"X mismatch for ({px}, {py}): got {recon_x}"
        assert recon_y == py, f"Y mismatch for ({px}, {py}): got {recon_y}"
        assert 0 <= nx <= 65535
        assert 0 <= ny <= 65535


def test_normalize_coordinates_origin_and_extremes(single_monitor_mouse_controller):
    """
    Tests screen origin (0, 0), rightmost/bottommost pixels, and corners.
    Verifies valid bounds and exact reconstruction.
    """
    w, h = 1920, 1080
    extreme_coords = [
        (0, 0),          # Origin
        (1919, 0),       # Top-right corner
        (0, 1079),       # Bottom-left corner
        (1919, 1079),    # Bottom-right corner (max in-bounds pixels)
    ]
    for px, py in extreme_coords:
        nx, ny = single_monitor_mouse_controller._normalize_coordinates(ScreenPoint(x=px, y=py))
        recon_x = (nx * w) >> 16
        recon_y = (ny * h) >> 16
        
        assert recon_x == px, f"Extreme X mismatch for ({px}, {py}): got {recon_x}"
        assert recon_y == py, f"Extreme Y mismatch for ({px}, {py}): got {recon_y}"
        assert 0 <= nx <= 65535
        assert 0 <= ny <= 65535


def test_consistent_normalization_between_move_and_click(single_monitor_mouse_controller):
    """Verifies that actuate_move and actuate_click use identical normalized coordinates."""
    captured_inputs = []
    
    def capture_send_input(n, p_inputs, size):
        # Read the MOUSEINPUT fields from the ctypes pointer
        lp_input = p_inputs._obj
        for inp in lp_input:
            mi = inp.union.mi
            captured_inputs.append((mi.dx, mi.dy, mi.dwFlags))
        return n
        
    single_monitor_mouse_controller.user32.SendInput.side_effect = capture_send_input
    
    target = ScreenPoint(x=759, y=721)
    
    # 1. Move
    single_monitor_mouse_controller.actuate_move(target)
    move_dx, move_dy, _ = captured_inputs[0]
    
    # 2. Click
    captured_inputs.clear()
    single_monitor_mouse_controller.actuate_click(target)
    # actuate_click calls actuate_move first, then down and up
    # All 3 should have identical dx, dy
    click_move_dx, click_move_dy, _ = captured_inputs[0]
    click_down_dx, click_down_dy, _ = captured_inputs[1]
    click_up_dx, click_up_dy, _ = captured_inputs[2]
    
    assert move_dx == click_move_dx == click_down_dx == click_up_dx
    assert move_dy == click_move_dy == click_down_dy == click_up_dy


def test_actuate_move_rejected_input(single_monitor_mouse_controller):
    """When SendInput returns 0, actuate_move returns ACTUATION_FAILURE with success=False."""
    single_monitor_mouse_controller.user32.SendInput.side_effect = lambda n, p, s: 0
    
    result = single_monitor_mouse_controller.actuate_move(ScreenPoint(x=500, y=500))
    assert result["success"] is False
    assert result["error"]["code"] == "ACTUATION_FAILURE"
    assert result["verified"] == TriState.UNKNOWN


def test_actuate_move_verification_states(single_monitor_mouse_controller):
    """Tests actuate_move with explicit verify=True for exact match, mismatch, and unavailable observation."""
    target = ScreenPoint(x=759, y=721)
    
    # Case A: Exact match observed
    with patch.object(single_monitor_mouse_controller, "get_cursor_pos_safe", return_value=(True, ScreenPoint(x=759, y=721))):
        res = single_monitor_mouse_controller.actuate_move(target, verify=True)
        assert res["success"] is True
        assert res["actuation_status"] == "ACTUATION_ACCEPTED"
        assert res["verified"] == TriState.TRUE
        assert res["observed_point"] == {"x": 759, "y": 721}
        
    # Case B: Verified mismatch observed
    with patch.object(single_monitor_mouse_controller, "get_cursor_pos_safe", return_value=(True, ScreenPoint(x=758, y=720))):
        res = single_monitor_mouse_controller.actuate_move(target, verify=True)
        assert res["success"] is True
        assert res["actuation_status"] == "ACTUATION_ACCEPTED"
        assert res["verified"] == TriState.FALSE
        assert res["error"]["code"] == "VERIFIED_MISMATCH"
        assert res["error"]["discrepancy"] == {"x": -1, "y": -1}
        assert res["observed_point"] == {"x": 758, "y": 720}
        
    # Case C: Observation unavailable (e.g. GetCursorPos failed)
    with patch.object(single_monitor_mouse_controller, "get_cursor_pos_safe", return_value=(False, ScreenPoint(x=0, y=0))):
        res = single_monitor_mouse_controller.actuate_move(target, verify=True)
        assert res["success"] is True
        assert res["actuation_status"] == "ACTUATION_ACCEPTED"
        assert res["verified"] == TriState.UNKNOWN
        assert res["error"]["code"] == "OBSERVATION_UNAVAILABLE"
