import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

from app.domain.entities import TriState
from app.domain.goals import FailureClass
from app.domain.visual import VisualObservation
from app.interaction.input.mouse_controller import (
    MouseController,
    ScreenPoint,
    MOUSEEVENTF_RIGHTDOWN,
    MOUSEEVENTF_RIGHTUP,
    MOUSEEVENTF_WHEEL,
    MOUSEEVENTF_HWHEEL,
    WHEEL_DELTA,
)
from app.interaction.router import InteractionRouter
from app.tools.builtin.physical_input import ExecutePhysicalInputTool
from app.ai.orchestrator.verification import VerificationEngine


# ============================================================================
# 1. MOUSE CONTROLLER: RIGHT CLICK
# ============================================================================

def test_actuate_right_click_success(monkeypatch):
    controller = MouseController()
    monkeypatch.setattr(controller, "_is_valid_coordinate", lambda pt: True)
    monkeypatch.setattr(controller, "actuate_move", lambda pt, verify=False: {"success": True})
    monkeypatch.setattr(controller, "get_cursor_pos_safe", lambda: (True, ScreenPoint(x=300, y=200)))

    sent_inputs = []
    def mock_send(inputs):
        for inp in inputs:
            sent_inputs.append((inp.union.mi.dwFlags, inp.union.mi.dx, inp.union.mi.dy))
        return True

    monkeypatch.setattr(controller, "_send_input", mock_send)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    res = controller.actuate_right_click(ScreenPoint(x=300, y=200))
    assert res["success"] is True
    assert res["action"] == "RIGHT_CLICK"
    assert res["diagnostics"]["dwell_ms"] == 60
    assert res["diagnostics"]["cursor_discrepancy"] == {"x": 0, "y": 0}

    # Verify flags sent: down then up
    assert len(sent_inputs) == 2
    assert sent_inputs[0][0] & MOUSEEVENTF_RIGHTDOWN
    assert sent_inputs[1][0] & MOUSEEVENTF_RIGHTUP


def test_actuate_right_click_guaranteed_release_on_error(monkeypatch):
    controller = MouseController()
    monkeypatch.setattr(controller, "_is_valid_coordinate", lambda pt: True)
    monkeypatch.setattr(controller, "actuate_move", lambda pt, verify=False: {"success": True})
    monkeypatch.setattr(controller, "get_cursor_pos_safe", lambda: (True, ScreenPoint(x=100, y=100)))

    sent_flags = []
    call_count = 0
    def mock_send(inputs):
        nonlocal call_count
        call_count += 1
        for inp in inputs:
            sent_flags.append(inp.union.mi.dwFlags)
        if call_count == 1:
            raise RuntimeError("OS fault during dwell")
        return True

    monkeypatch.setattr(controller, "_send_input", mock_send)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    with pytest.raises(RuntimeError):
        controller.actuate_right_click(ScreenPoint(x=100, y=100))

    # Button release MUST still be sent via try...finally
    assert any(f & MOUSEEVENTF_RIGHTUP for f in sent_flags)


# ============================================================================
# 2. MOUSE CONTROLLER: SCROLL
# ============================================================================

def test_actuate_scroll_vertical_positive_and_negative(monkeypatch):
    controller = MouseController()
    sent_inputs = []

    def mock_send(inputs):
        for inp in inputs:
            sent_inputs.append((inp.union.mi.dwFlags, inp.union.mi.mouseData))
        return True

    monkeypatch.setattr(controller, "_send_input", mock_send)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    # 1. Scroll Up 3 clicks
    sent_inputs.clear()
    res_up = controller.actuate_scroll(clicks=3)
    assert res_up["success"] is True
    assert res_up["diagnostics"]["effective_vertical_clicks"] == 3
    assert len(sent_inputs) == 1
    assert sent_inputs[0][0] == MOUSEEVENTF_WHEEL
    assert sent_inputs[0][1] == 3 * WHEEL_DELTA

    # 2. Scroll Down 2 clicks (negative delta masked to unsigned 32-bit DWORD)
    sent_inputs.clear()
    res_down = controller.actuate_scroll(clicks=-2)
    assert res_down["success"] is True
    assert res_down["diagnostics"]["effective_vertical_clicks"] == -2
    assert len(sent_inputs) == 1
    assert sent_inputs[0][0] == MOUSEEVENTF_WHEEL
    expected_data = (-2 * WHEEL_DELTA) & 0xFFFFFFFF
    assert sent_inputs[0][1] == expected_data


def test_actuate_scroll_horizontal(monkeypatch):
    controller = MouseController()
    sent_inputs = []

    def mock_send(inputs):
        for inp in inputs:
            sent_inputs.append((inp.union.mi.dwFlags, inp.union.mi.mouseData))
        return True

    monkeypatch.setattr(controller, "_send_input", mock_send)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    res = controller.actuate_scroll(delta_x=2)
    assert res["success"] is True
    assert len(sent_inputs) == 1
    assert sent_inputs[0][0] == MOUSEEVENTF_HWHEEL
    assert sent_inputs[0][1] == 2 * WHEEL_DELTA


def test_actuate_scroll_preposition_move(monkeypatch):
    controller = MouseController()
    monkeypatch.setattr(controller, "_is_valid_coordinate", lambda pt: True)
    move_called_with = None

    def mock_move(pt, verify=True):
        nonlocal move_called_with
        move_called_with = pt
        return {"success": True}

    monkeypatch.setattr(controller, "actuate_move", mock_move)
    monkeypatch.setattr(controller, "_send_input", lambda inp: True)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    res = controller.actuate_scroll(clicks=1, point=ScreenPoint(x=450, y=350))
    assert res["success"] is True
    assert move_called_with is not None
    assert move_called_with.x == 450
    assert move_called_with.y == 350


# ============================================================================
# 3. MOUSE CONTROLLER: DRAG
# ============================================================================

def test_actuate_drag_interpolation_and_guaranteed_release(monkeypatch):
    controller = MouseController()
    monkeypatch.setattr(controller, "_is_valid_coordinate", lambda pt: True)
    
    moves = []
    monkeypatch.setattr(controller, "actuate_move", lambda pt, verify=False: moves.append((pt.x, pt.y)) or {"success": True})

    sent_flags = []
    def mock_send(inputs):
        for inp in inputs:
            sent_flags.append(inp.union.mi.dwFlags)
        return True

    monkeypatch.setattr(controller, "_send_input", mock_send)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    start = ScreenPoint(x=100, y=100)
    end = ScreenPoint(x=200, y=300)
    res = controller.actuate_drag(start_point=start, end_point=end, steps=5, duration_ms=50)

    assert res["success"] is True
    assert res["diagnostics"]["steps_executed"] == 5
    # Move to start + 5 interpolation steps = 6 moves
    assert len(moves) == 6
    assert moves[0] == (100, 100)
    assert moves[-1] == (200, 300)

    # Down at start, Up at end
    assert len(sent_flags) == 2


def test_actuate_drag_guaranteed_release_on_intermediate_exception(monkeypatch):
    """
    Guarantees mouse button release is strictly sent even if an intermediate operation
    (e.g., move interpolation, thread interruption) raises an unhandled exception.
    """
    controller = MouseController()
    monkeypatch.setattr(controller, "_is_valid_coordinate", lambda pt: True)
    monkeypatch.setattr(controller, "_ensure_window_activated", lambda pt: (0, 0, False))

    call_count = 0
    def failing_move(pt, verify=False):
        nonlocal call_count
        call_count += 1
        if call_count > 1: # Fail during interpolation
            raise RuntimeError("Hardware communication error during drag move")
        return {"success": True}

    monkeypatch.setattr(controller, "actuate_move", failing_move)

    sent_flags = []
    def mock_send(inputs):
        for inp in inputs:
            sent_flags.append(inp.union.mi.dwFlags)
        return True

    monkeypatch.setattr(controller, "_send_input", mock_send)
    monkeypatch.setattr(controller, "_with_dpi_awareness", lambda fn: fn())

    start = ScreenPoint(x=100, y=100)
    end = ScreenPoint(x=300, y=300)
    res = controller.actuate_drag(start_point=start, end_point=end, steps=5, duration_ms=50)

    # Actuation reported failure due to exception
    assert res["success"] is False
    assert "Exception during mouse drag" in res["error"]["message"]
    # But button-up input is GUARANTEED to have been sent in finally: block
    assert res["diagnostics"]["button_down_accepted"] is True
    assert res["diagnostics"]["button_up_accepted"] is True
    assert len(sent_flags) == 2


# ============================================================================
# 4. TOOL SCHEMA & ROUTING
# ============================================================================

@pytest.mark.asyncio
async def test_physical_input_tool_schema_and_execution(monkeypatch):
    tool = ExecutePhysicalInputTool()
    assert "RIGHT_CLICK" in tool.schema["properties"]["intent"]["enum"]
    assert "SCROLL" in tool.schema["properties"]["intent"]["enum"]
    assert "DRAG" in tool.schema["properties"]["intent"]["enum"]
    assert "start_x" in tool.schema["properties"]
    assert "start_y" in tool.schema["properties"]
    assert "duration_ms" in tool.schema["properties"]

    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "SCROLL"}
    monkeypatch.setattr("app.interaction.router.interaction_router", mock_router)

    res = await tool.execute(intent="SCROLL", clicks=5, delta_x=1)
    assert res["success"] is True
    mock_router.route.assert_awaited_once_with(
        "SCROLL",
        target_entity=None,
        hwnds=None,
        pids=None,
        point=None,
        text=None,
        key=None,
        keys=None,
        clicks=5,
        delta_x=1,
        delta_y=0,
    )

    mock_router.reset_mock()
    mock_router.route.return_value = {"success": True, "action": "DRAG"}
    res_drag = await tool.execute(intent="DRAG", start_x=15, start_y=25, end_x=115, end_y=125, duration_ms=300)
    assert res_drag["success"] is True
    mock_router.route.assert_awaited_once_with(
        "DRAG",
        target_entity=None,
        hwnds=None,
        pids=None,
        point=ScreenPoint(x=15, y=25),
        text=None,
        key=None,
        keys=None,
        end_point=ScreenPoint(x=115, y=125),
        button="left",
        steps=10,
        duration_ms=300,
    )


@pytest.mark.asyncio
async def test_interaction_router_dispatches_scroll_drag_right_click(monkeypatch):
    router = InteractionRouter()
    
    mock_mc = MagicMock()
    mock_mc.actuate_scroll.return_value = {"success": True, "action": "SCROLL"}
    mock_mc.actuate_drag.return_value = {"success": True, "action": "DRAG"}
    mock_mc.actuate_right_click.return_value = {"success": True, "action": "RIGHT_CLICK"}
    monkeypatch.setattr("app.interaction.router.mouse_controller", mock_mc)

    # Test RIGHT_CLICK dispatch
    res_rc = await router.route("RIGHT_CLICK", point=ScreenPoint(x=10, y=20))
    assert res_rc["success"] is True
    mock_mc.actuate_right_click.assert_called_once()

    # Test SCROLL dispatch
    res_sc = await router.route("SCROLL", clicks=3, delta_x=1)
    assert res_sc["success"] is True
    mock_mc.actuate_scroll.assert_called_once_with(clicks=3, delta_x=1, delta_y=0, point=None)

    # Test DRAG dispatch
    res_dg = await router.route("DRAG", point=ScreenPoint(x=10, y=10), end_point=ScreenPoint(x=50, y=50))
    assert res_dg["success"] is True
    mock_mc.actuate_drag.assert_called_once()


# ============================================================================
# 5. VERIFICATION ENGINE: SCROLL & DRAG
# ============================================================================

def make_mock_obs(obs_id="obs_1", delta_seconds=0):
    base = datetime(2026, 10, 17, 12, 0, 0, tzinfo=timezone.utc)
    return VisualObservation(
        observation_id=obs_id,
        captured_at=base + timedelta(seconds=delta_seconds),
        image_reference=f"ref_{obs_id}",
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
    )


def test_verify_scroll_displacement():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets_before = [
        ([100, 200, 50, 20], "Header", 0.95),
        ([100, 250, 50, 20], "Item 1", 0.95),
        ([100, 300, 50, 20], "Item 2", 0.95),
    ]
    # Scrolled down: items moved up by 40px
    dets_after = [
        ([100, 160, 50, 20], "Header", 0.95),
        ([100, 210, 50, 20], "Item 1", 0.95),
        ([100, 260, 50, 20], "Item 2", 0.95),
    ]

    res = VerificationEngine.verify_scroll(
        obs_before=obs_before,
        obs_after=obs_after,
        detections_before=dets_before,
        detections_after=dets_after,
    )
    assert res.verified == TriState.TRUE
    assert res.actual_state == "Viewport Displaced"
    assert "average dy=-40.0px" in res.evidence


def test_verify_scroll_stationary_failure():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets = [
        ([100, 200, 50, 20], "Header", 0.95),
        ([100, 250, 50, 20], "Item 1", 0.95),
        ([100, 300, 50, 20], "Item 2", 0.95),
    ]

    res = VerificationEngine.verify_scroll(
        obs_before=obs_before,
        obs_after=obs_after,
        detections_before=dets,
        detections_after=dets,
    )
    assert res.verified == TriState.FALSE
    assert res.actual_state == "Stationary Viewport"
    assert res.failure_code == FailureClass.CLICK_NO_EFFECT


def test_verify_scroll_stale_observation():
    obs_before = make_mock_obs("obs_1", delta_seconds=10)
    obs_after = make_mock_obs("obs_2", delta_seconds=5)

    res = VerificationEngine.verify_scroll(
        obs_before=obs_before,
        obs_after=obs_after,
        detections_before=[],
        detections_after=[],
    )
    assert res.verified == TriState.UNKNOWN
    assert res.failure_code == FailureClass.STALE_TARGET


def test_verify_drag_success_and_failure():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets_before = [
        ([100, 200, 80, 40], "Project_Folder", 0.95),
        ([100, 100, 50, 20], "Trash", 0.95),
    ]

    # Item moved to destination (500, 400, 80, 40)
    dets_success = [
        ([505, 405, 80, 40], "Project_Folder", 0.95),
        ([100, 100, 50, 20], "Trash", 0.95),
    ]

    res_ok = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Project_Folder",
        expected_destination_bounds=(500, 400, 80, 40),
        detections_before=dets_before,
        detections_after=dets_success,
    )
    assert res_ok.verified == TriState.TRUE
    assert "Element at Destination" in res_ok.actual_state

    # Item dropped outside destination
    dets_wrong_landing = [
        ([200, 200, 80, 40], "Project_Folder", 0.95),
        ([100, 100, 50, 20], "Trash", 0.95),
    ]
    res_fail = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Project_Folder",
        expected_destination_bounds=(500, 400, 80, 40),
        detections_before=dets_before,
        detections_after=dets_wrong_landing,
    )
    assert res_fail.verified == TriState.FALSE
    assert res_fail.failure_code == FailureClass.VERIFICATION_FAILED


def test_verify_drag_rejects_stationary_target_at_destination():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    # Element was already stationary at destination before drag
    dets_before = [
        ([505, 405, 80, 40], "Project_Folder", 0.95),
    ]
    dets_after = [
        ([505, 405, 80, 40], "Project_Folder", 0.95),
    ]

    res = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Project_Folder",
        expected_destination_bounds=(500, 400, 80, 40),
        detections_before=dets_before,
        detections_after=dets_after,
    )
    assert res.verified == TriState.FALSE
    assert res.failure_code == FailureClass.CLICK_NO_EFFECT
    assert "already stationary" in res.evidence


def test_verify_drag_insufficient_evidence_returns_unknown():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets_after = [
        ([505, 405, 80, 40], "Project_Folder", 0.95),
    ]

    # detections_before is omitted: conservative verifier returns UNKNOWN
    res = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Project_Folder",
        expected_destination_bounds=(500, 400, 80, 40),
        detections_before=None,
        detections_after=dets_after,
    )
    assert res.verified == TriState.UNKNOWN
    assert res.failure_code == FailureClass.UNKNOWN
    assert "prior detections (detections_before) were not provided" in res.evidence


def test_verify_drag_window_bounds_rejects_visual_false_positive():
    """
    Guarantees that a visual element detection (e.g. tab header or window title)
    cannot independently produce a false-positive result for a window title bar drag
    when the Win32 window remained stationary.
    """
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    # Window did NOT move (dx=0, dy=0)
    win_bounds_before = (200, 150, 800, 600)
    win_bounds_after = (200, 150, 800, 600)

    # Visual detection of window title happens to exist at destination
    dets_after = [
        ([350, 155, 100, 30], "Notepad - Untitled", 0.95),
    ]

    res = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Notepad - Untitled",
        expected_destination_bounds=(350, 155, 100, 30),
        window_bounds_before=win_bounds_before,
        window_bounds_after=win_bounds_after,
        detections_after=dets_after,
    )
    assert res.verified == TriState.FALSE
    assert res.failure_code == FailureClass.CLICK_NO_EFFECT
    assert "window remained stationary" in res.evidence
    assert "Visual detections near destination cannot independently validate window title bar drag" in res.evidence


def test_verify_drag_window_bounds_success_and_reverse_restoration():
    """
    Verifies that window displacement is authoritatively verified via Win32 bounds,
    and a reverse drag restores the original window position.
    """
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    initial_pos = (100, 100, 800, 600)
    dragged_pos = (250, 150, 800, 600)

    # Forward drag: displacement = hypot(150, 50) = 158.1px
    res_fwd = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Notepad",
        window_bounds_before=initial_pos,
        window_bounds_after=dragged_pos,
    )
    assert res_fwd.verified == TriState.TRUE
    assert "dx=150px, dy=50px" in res_fwd.evidence

    # Reverse drag: restores original window position
    res_rev = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="Notepad",
        window_bounds_before=dragged_pos,
        window_bounds_after=initial_pos,
    )
    assert res_rev.verified == TriState.TRUE
    assert "dx=-150px, dy=-50px" in res_rev.evidence



def test_verify_drag_text_selection_clipboard():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    # Text selection drag verified via clipboard text copy match
    res = VerificationEngine.verify_drag(
        obs_before=obs_before,
        obs_after=obs_after,
        target_label="unique_token_123",
        clipboard_text="Astra Scroll unique_token_123 Line 01 Payload",
    )
    assert res.verified == TriState.TRUE
    assert "Text Selected" in res.actual_state
    assert "Authoritative OS clipboard proof" in res.evidence


def test_verify_scroll_cross_column_matching_insulation():
    """
    Guarantees that duplicate tokens across distant columns (e.g. x=270 vs x=1580)
    do not cross-pair to create artificial horizontal displacement (e.g. dx=-1310px).
    """
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets_before = [
        ([270, 200, 50, 20], "Payload", 0.95),
        ([1580, 200, 50, 20], "Payload", 0.95),
        ([270, 250, 50, 20], "Line 1", 0.95),
    ]
    # Scrolled down by 50px (y shifts from 200 to 150)
    dets_after = [
        ([270, 150, 50, 20], "Payload", 0.95),
        ([1580, 200, 50, 20], "Payload", 0.95),
        ([270, 200, 50, 20], "Line 1", 0.95),
    ]

    res = VerificationEngine.verify_scroll(
        obs_before=obs_before,
        obs_after=obs_after,
        detections_before=dets_before,
        detections_after=dets_after,
    )
    assert res.verified == TriState.TRUE
    assert res.actual_state == "Viewport Displaced"
    # Validates dx is 0.0px, NOT -1310.0px!
    assert "dx=0.0px" in res.evidence
    assert "average dy=-33.3px" in res.evidence


def test_verify_context_menu_success_with_authoritative_phrase():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets_before = [([100, 100, 80, 20], "Document Content", 0.95)]
    dets_after = [
        ([100, 100, 80, 20], "Document Content", 0.95),
        ([310, 210, 90, 25], "Select all", 0.95),
        ([310, 240, 60, 25], "Font...", 0.95),
    ]

    res = VerificationEngine.verify_context_menu(
        obs_before=obs_before,
        obs_after=obs_after,
        click_point=(300, 200),
        window_bounds=(50, 50, 1000, 800),
        detections_before=dets_before,
        detections_after=dets_after,
    )
    assert res.verified == TriState.TRUE
    assert res.actual_state == "Context Menu Opened: 'Select all'"
    assert "Select all" in res.evidence


def test_verify_context_menu_success_with_corroborating_tokens():
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    dets_after = [
        ([310, 210, 50, 20], "Select", 0.95),
        ([370, 210, 30, 20], "All", 0.95),
        ([310, 240, 40, 20], "Paste", 0.95),
    ]

    res = VerificationEngine.verify_context_menu(
        obs_before=obs_before,
        obs_after=obs_after,
        click_point=(300, 200),
        window_bounds=(50, 50, 1000, 800),
        detections_before=[],
        detections_after=dets_after,
    )
    assert res.verified == TriState.TRUE
    assert "corroborating tokens" in res.evidence


def test_verify_context_menu_rejects_isolated_noise_fragment():
    """
    Specifically tests that an isolated 2-letter OCR fragment like 'Ot'
    is rejected and does not manufacture false context menu verification.
    """
    obs_before = make_mock_obs("obs_1", delta_seconds=0)
    obs_after = make_mock_obs("obs_2", delta_seconds=1)

    # Only a spurious 2-letter noise fragment 'Ot' near the click point
    dets_after = [
        ([310, 210, 15, 12], "Ot", 0.50),
    ]

    res = VerificationEngine.verify_context_menu(
        obs_before=obs_before,
        obs_after=obs_after,
        click_point=(300, 200),
        window_bounds=(50, 50, 1000, 800),
        detections_before=[],
        detections_after=dets_after,
    )
    assert res.verified == TriState.FALSE
    assert res.actual_state == "Uncorroborated Fragment / No Menu"
    assert "candidate 'Ot' does not satisfy corroboration threshold" in res.evidence


# ============================================================================
# 6. RESILIENCY & LIVE SCRIPT REGRESSION GUARD
# ============================================================================

def test_desktop_controller_resilient_aliases():
    from app.tools.desktop.desktop_controller import desktop_controller, ApplicationIntent
    assert hasattr(desktop_controller, "get_application_status")
    assert hasattr(desktop_controller, "query_application_state")
    assert hasattr(desktop_controller, "execute_intent")
    assert hasattr(desktop_controller, "resolve_application_intent")


@pytest.mark.asyncio
async def test_live_scroll_drag_script_execution_mocked(monkeypatch):
    """
    Guarantees that test_live_scroll_drag_interaction.py has valid imports,
    correct method signatures, and executes all 8 stages without AttributeError or NameError.
    """
    from tests.live.test_live_scroll_drag_interaction import run_live_scroll_drag_test
    from app.domain.visual import VisualObservation

    # Mock environment diagnostic
    monkeypatch.setattr(
        "tests.live.test_live_scroll_drag_interaction.diagnose_environment",
        lambda: {
            "execution_context_synthesis": {"summary": "INTERACTIVE_DESKTOP"},
            "station_and_desktop": {
                "thread_desktop_name": "Default",
                "active_input_desktop_name": "Default",
                "is_on_active_input_desktop": True,
            },
        },
    )

    # Mock desktop controller
    mock_dc = MagicMock()
    mock_dc.get_application_status.return_value = {
        "state": "RUNNING_FOREGROUND",
        "installed": True,
        "windows": [{"hwnd": 12345, "title": "Notepad", "bounds": {"x": 100, "y": 100, "width": 800, "height": 600}}],
    }
    mock_dc.execute_intent = AsyncMock(return_value={"success": True})
    monkeypatch.setattr("app.tools.desktop.desktop_controller.desktop_controller", mock_dc)

    # Mock window manager
    mock_wm = MagicMock()
    mock_wm.user32 = None
    mock_wm.get_active_window.return_value = 12345
    monkeypatch.setattr("app.environment.window.manager.window_manager", mock_wm)

    # Mock action executor with dynamic text capture
    captured_payload = [""]
    mock_ae = MagicMock()
    async def mock_exec(intent, tool_args=None, **kwargs):
        if tool_args and tool_args.get("intent") == "TYPE_TEXT":
            captured_payload[0] = tool_args.get("text", "")
        return {"success": True, "action": "MOCKED"}
    mock_ae.execute_intent = mock_exec
    monkeypatch.setattr("app.ai.orchestrator.action_executor.action_executor", mock_ae)

    # Mock clipboard helpers
    monkeypatch.setattr("tests.live.test_live_scroll_drag_interaction.clear_clipboard", lambda: True)
    monkeypatch.setattr(
        "tests.live.test_live_scroll_drag_interaction.get_clipboard_text",
        lambda: captured_payload[0].split("\n")[0] if captured_payload[0] else "Astra Scroll Mock",
    )

    # Mock screen capture provider & store
    mock_scp = MagicMock()
    obs_count = 0
    def mock_capture(obs_id):
        nonlocal obs_count
        obs_count += 1
        return VisualObservation(
            observation_id=obs_id,
            captured_at=datetime(2026, 10, 17, 12, 0, obs_count, tzinfo=timezone.utc),
            image_reference=f"ref_{obs_id}",
            width=1920,
            height=1080,
            virtual_offset_x=0,
            virtual_offset_y=0,
            pixel_format="BGRA",
        )
    mock_scp.capture_virtual_screen.side_effect = mock_capture
    mock_scp.store.retrieve.return_value = b"\x00" * 100
    monkeypatch.setattr("app.environment.visual.capture.screen_capture_provider", mock_scp)

    # Mock window bounds tracking
    monkeypatch.setattr("tests.live.test_live_scroll_drag_interaction.get_window_bounds", lambda hwnd: (100, 100, 800, 600))

    # Mock OCR perception
    ocr_calls = 0
    def mock_ocr(img_bytes, w, h):
        nonlocal ocr_calls
        ocr_calls += 1
        line_sample = captured_payload[0].split("\n")[0] if captured_payload[0] else "Astra Scroll Line 01 Payload"
        if ocr_calls == 1:
            # Stage 3: before scroll
            return [
                ([150, 200, 100, 20], line_sample, 0.95),
                ([150, 240, 100, 20], line_sample.replace("Line 01", "Line 02"), 0.95),
            ]
        elif ocr_calls == 2:
            # Stage 5: after scroll (lines shifted up by 50px)
            return [
                ([150, 150, 100, 20], line_sample, 0.95),
                ([150, 190, 100, 20], line_sample.replace("Line 01", "Line 02"), 0.95),
            ]
        elif ocr_calls == 3:
            # Stage 7: post-drag observation (text selected)
            return [
                ([150, 150, 100, 20], line_sample, 0.95),
            ]
        elif ocr_calls == 4:
            # Stage 8: pre-right-click
            return [
                ([150, 150, 100, 20], line_sample, 0.95),
            ]
        elif ocr_calls == 5:
            # Stage 8: post-right-click (context menu opened)
            return [
                ([380, 320, 90, 25], "Select all", 0.95),
                ([380, 350, 60, 25], "Font...", 0.95),
            ]
        else:
            # Stage 9: clean buffer with standard UI elements
            return [
                ([100, 50, 30, 20], "File", 0.95),
                ([140, 50, 30, 20], "Edit", 0.95),
                ([180, 50, 30, 20], "View", 0.95),
                ([200, 20, 80, 20], "Untitled", 0.95),
                ([500, 800, 50, 20], "Ln 1, Col 1", 0.95),
            ]

    monkeypatch.setattr("app.environment.visual.perception._run_windows_media_ocr", mock_ocr)

    # Mock keyboard controller
    mock_kc = MagicMock()
    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller", mock_kc)

    # Run the live test with opt_in_confirmed=True
    exit_code = await run_live_scroll_drag_test(opt_in_confirmed=True)
    assert exit_code == 0

