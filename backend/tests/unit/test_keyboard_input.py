"""
ASTRA — Phase B.4 Unit Regression Suite: Universal Physical Keyboard & Text Input Foundation
"""

import pytest
import datetime
from unittest.mock import MagicMock, patch, AsyncMock
from app.domain.entities import TriState
from app.domain.goals import FailureClass
from app.domain.visual import VisualObservation
from app.interaction.input.keyboard_controller import (
    KeyboardController,
    INPUT,
    KEYBDINPUT,
    INPUT_KEYBOARD,
    KEYEVENTF_UNICODE,
    KEYEVENTF_KEYUP,
    VK_RETURN,
    VK_TAB,
    VK_CONTROL,
    VK_SHIFT,
    VK_BACK,
)
from app.tools.builtin.physical_input import ExecutePhysicalInputTool
from app.tools.schemas import ToolRisk
from app.ai.orchestrator.verification import VerificationEngine


def make_obs(obs_id: str, delta_seconds: float = 0.0) -> VisualObservation:
    base = datetime.datetime(2026, 10, 17, 12, 0, 0, tzinfo=datetime.timezone.utc)
    return VisualObservation(
        observation_id=obs_id,
        captured_at=base + datetime.timedelta(seconds=delta_seconds),
        image_reference=f"ref_{obs_id}",
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
    )


# =============================================================================
# 1. KeyboardController Key Resolution & Invariant Tests
# =============================================================================

def test_keyboard_controller_struct_size():
    """Confirms Win32 tagINPUT 40-byte invariant on 64-bit platform."""
    import ctypes
    assert ctypes.sizeof(INPUT) == 40
    assert ctypes.sizeof(KEYBDINPUT) == 24


def test_keyboard_controller_resolve_key_code():
    kc = KeyboardController()
    vk_enter, _ = kc.resolve_key_code("enter")
    assert vk_enter == VK_RETURN

    vk_tab, _ = kc.resolve_key_code("tab")
    assert vk_tab == VK_TAB

    vk_ctrl, _ = kc.resolve_key_code("ctrl")
    assert vk_ctrl == VK_CONTROL

    vk_back, _ = kc.resolve_key_code("backspace")
    assert vk_back == VK_BACK

    vk_a, _ = kc.resolve_key_code("a")
    assert vk_a == ord("A")

    vk_unknown, scan_unknown = kc.resolve_key_code("nonexistent_key_xyz")
    assert vk_unknown == 0
    assert scan_unknown == 0


def test_keyboard_controller_type_char_unicode_packets(monkeypatch):
    """Verifies that type_char_unicode sends KEYEVENTF_UNICODE with wVk=0 and wScan=ord(c)."""
    kc = KeyboardController()
    sent_inputs = []

    def mock_send(inputs):
        sent_inputs.extend(inputs)
        return True

    monkeypatch.setattr(kc, "_send_input", mock_send)
    monkeypatch.setattr("time.sleep", lambda s: None)

    ok = kc.type_char_unicode("Z")
    assert ok is True
    assert len(sent_inputs) == 2  # down, then up

    down = sent_inputs[0]
    up = sent_inputs[1]
    assert down.type == INPUT_KEYBOARD
    assert down.union.ki.wVk == 0
    assert down.union.ki.wScan == ord("Z")
    assert down.union.ki.dwFlags == KEYEVENTF_UNICODE

    assert up.type == INPUT_KEYBOARD
    assert up.union.ki.wVk == 0
    assert up.union.ki.wScan == ord("Z")
    assert up.union.ki.dwFlags == (KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)


def test_keyboard_controller_type_char_newline_and_tab(monkeypatch):
    """Verifies that newline and tab are translated to virtual keys VK_RETURN and VK_TAB."""
    kc = KeyboardController()
    sent_keys = []

    def mock_actuate_key(vk, scan_code=0, dwell_ms=50):
        sent_keys.append(vk)
        return {"success": True, "action": "KEY_PRESS", "vk": vk}

    monkeypatch.setattr(kc, "actuate_key", mock_actuate_key)

    kc.type_char_unicode("\n")
    assert VK_RETURN in sent_keys

    sent_keys.clear()
    kc.type_char_unicode("\t")
    assert VK_TAB in sent_keys


def test_keyboard_controller_type_text(monkeypatch):
    """Verifies type_text types entire string with character count and unknown verification."""
    kc = KeyboardController()
    typed_chars = []

    def mock_type_char(char, dwell_ms=20):
        typed_chars.append(char)
        return True

    monkeypatch.setattr(kc, "type_char_unicode", mock_type_char)
    monkeypatch.setattr("time.sleep", lambda s: None)

    res = kc.type_text("Hello ASTRA 123", cpm=1200)
    assert res["success"] is True
    assert res["action"] == "TYPE_TEXT"
    assert res["char_count"] == 15
    assert res["verified"] == TriState.UNKNOWN
    assert "".join(typed_chars) == "Hello ASTRA 123"


def test_keyboard_controller_actuate_hotkey_ordering_and_guaranteed_release(monkeypatch):
    """Verifies hotkey presses keys in order and guarantees reverse-order release."""
    kc = KeyboardController()
    events = []

    def mock_send(inputs):
        for inp in inputs:
            is_up = bool(inp.union.ki.dwFlags & KEYEVENTF_KEYUP)
            vk = inp.union.ki.wVk
            events.append((vk, "UP" if is_up else "DOWN"))
        return True

    monkeypatch.setattr(kc, "_send_input", mock_send)
    monkeypatch.setattr("time.sleep", lambda s: None)

    res = kc.actuate_hotkey(["ctrl", "shift", "s"])
    assert res["success"] is True
    assert res["action"] == "HOTKEY"

    # Press down: ctrl, shift, S
    assert events[0] == (VK_CONTROL, "DOWN")
    assert events[1] == (VK_SHIFT, "DOWN")
    assert events[2] == (ord("S"), "DOWN")

    # Release up: S, shift, ctrl (reverse order)
    assert events[3] == (ord("S"), "UP")
    assert events[4] == (VK_SHIFT, "UP")
    assert events[5] == (VK_CONTROL, "UP")


def test_keyboard_controller_actuate_hotkey_error_handling(monkeypatch):
    kc = KeyboardController()
    res_empty = kc.actuate_hotkey([])
    assert res_empty["success"] is False
    assert res_empty["error"]["code"] == "EMPTY_HOTKEY"

    res_unknown = kc.actuate_hotkey(["ctrl", "unknown_key_foobar"])
    assert res_unknown["success"] is False
    assert res_unknown["error"]["code"] == "UNKNOWN_KEY"


# =============================================================================
# 2. Tool & Router Integration Tests
# =============================================================================

@pytest.mark.asyncio
async def test_execute_physical_input_tool_type_text(monkeypatch):
    tool = ExecutePhysicalInputTool()
    assert "TYPE_TEXT" in tool.schema["properties"]["intent"]["enum"]
    assert "text" in tool.schema["properties"]
    assert "physical.keyboard_input" in tool.capabilities

    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "TYPE_TEXT", "char_count": 5}
    monkeypatch.setattr("app.interaction.router.interaction_router", mock_router)

    res = await tool.execute(intent="TYPE_TEXT", text="Hello")
    assert res["success"] is True
    mock_router.route.assert_awaited_once_with(
        "TYPE_TEXT",
        target_entity=None,
        hwnds=None,
        pids=None,
        point=None,
        text="Hello",
        key=None,
        keys=None,
    )


@pytest.mark.asyncio
async def test_execute_physical_input_tool_hotkey(monkeypatch):
    tool = ExecutePhysicalInputTool()
    assert "HOTKEY" in tool.schema["properties"]["intent"]["enum"]
    assert "keys" in tool.schema["properties"]

    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "HOTKEY", "keys": ["ctrl", "s"]}
    monkeypatch.setattr("app.interaction.router.interaction_router", mock_router)

    res = await tool.execute(intent="HOTKEY", keys=["ctrl", "s"])
    assert res["success"] is True
    mock_router.route.assert_awaited_once_with(
        "HOTKEY",
        target_entity=None,
        hwnds=None,
        pids=None,
        point=None,
        text=None,
        key=None,
        keys=["ctrl", "s"],
    )


@pytest.mark.asyncio
async def test_interaction_router_routes_type_text_and_hotkey(monkeypatch):
    from app.interaction.router import InteractionRouter
    router = InteractionRouter()

    mock_kc = MagicMock()
    mock_kc.type_text.return_value = {"success": True, "action": "TYPE_TEXT", "char_count": 4}
    mock_kc.actuate_hotkey.return_value = {"success": True, "action": "HOTKEY", "keys": ["ctrl", "c"]}
    mock_kc.actuate_special_key.return_value = {"success": True, "action": "KEY_PRESS", "key": "enter"}

    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller", mock_kc)

    res_type = await router.route("TYPE_TEXT", text="Test")
    assert res_type["success"] is True
    mock_kc.type_text.assert_called_once_with("Test")

    res_hotkey = await router.route("HOTKEY", keys=["ctrl", "c"])
    assert res_hotkey["success"] is True
    mock_kc.actuate_hotkey.assert_called_once_with(["ctrl", "c"])

    res_key = await router.route("PRESS_KEY", key="enter")
    assert res_key["success"] is True
    mock_kc.actuate_special_key.assert_called_once_with("enter")


# =============================================================================
# 3. VerificationEngine verify_text_input Regression Tests
# =============================================================================

def test_verify_text_input_success():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    detections = [
        ([100, 200, 150, 20], "Hello World", 0.99),
        ([500, 300, 80, 20], "Some other text", 0.95),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="Hello World",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
    )
    assert res.verified == TriState.TRUE
    assert "visibly confirmed" in res.evidence
    assert res.actual_state == "Text Present: 'Hello World'"


def test_verify_text_input_case_insensitive_substring():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    detections = [
        ([100, 200, 300, 20], "The user wrote ASTRA_PROMPT_123 in buffer", 0.99),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="astra_prompt_123",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
    )
    assert res.verified == TriState.TRUE


def test_verify_text_input_scoped_target_bounds():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    # Detection is at (1500, 900), outside window bounds (200, 100, 800, 600)
    detections = [
        ([1500, 900, 100, 20], "MyTargetText", 0.99),
        ([250, 150, 80, 20], "Unrelated A", 0.95),
        ([250, 200, 80, 20], "Unrelated B", 0.95),
        ([250, 250, 80, 20], "Unrelated C", 0.95),
        ([250, 300, 80, 20], "Unrelated D", 0.95),
        ([250, 350, 80, 20], "Unrelated E", 0.95),
    ]

    # Target text is outside the specified bounds -> verification fails
    res = VerificationEngine.verify_text_input(
        expected_text="MyTargetText",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
        target_bounds=(200, 100, 800, 600),
    )
    assert res.verified == TriState.FALSE
    assert res.actual_state == "Text Absent"


def test_verify_text_input_failure_when_absent():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    detections = [
        ([100, 100, 50, 20], "Doc 1", 0.9),
        ([100, 150, 50, 20], "Doc 2", 0.9),
        ([100, 200, 50, 20], "Doc 3", 0.9),
        ([100, 250, 50, 20], "Doc 4", 0.9),
        ([100, 300, 50, 20], "Doc 5", 0.9),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="SpecialTextXYZ",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
    )
    assert res.verified == TriState.FALSE
    assert res.actual_state == "Text Absent"
    assert res.failure_code == FailureClass.VERIFICATION_FAILED


def test_verify_text_input_stale_observation():
    obs_before = make_obs("obs_1", delta_seconds=1)
    obs_stale = make_obs("obs_stale", delta_seconds=0)
    detections = [([100, 200, 150, 20], "Hello", 0.99)] * 5

    res = VerificationEngine.verify_text_input(
        expected_text="Hello",
        obs_before=obs_before,
        obs_after=obs_stale,
        detections_after=detections,
    )
    assert res.verified == TriState.UNKNOWN
    assert res.actual_state == "Stale Observation"
    assert res.failure_code == FailureClass.STALE_TARGET


def test_verify_text_input_sparse_detections():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    detections = [([100, 100, 50, 20], "OnlyOneItem", 0.9)]

    res = VerificationEngine.verify_text_input(
        expected_text="SpecialTextXYZ",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
    )
    assert res.verified == TriState.UNKNOWN
    assert res.actual_state == "Ambiguous"


def test_verify_text_input_normalized_alphanumeric_matching():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    # OCR separated hyphens with spaces: "ASTRA - PHASE - B4 - 7c99a8"
    detections = [
        ([100, 200, 300, 20], "ASTRA - PHASE - B4 - 7c99a8", 0.99),
        ([100, 250, 100, 20], "Other line", 0.95),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="ASTRA-PHASE-B4-7c99a8",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
    )
    assert res.verified == TriState.TRUE
    assert res.actual_state == "Text Present: 'ASTRA - PHASE - B4 - 7c99a8'"


def test_verify_text_input_multi_word_composite_matching():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    # OCR split the phrase into individual word detections
    detections = [
        ([100, 200, 50, 20], "Astra", 0.99),
        ([160, 200, 40, 20], "Live", 0.99),
        ([210, 200, 80, 20], "Keyboard", 0.99),
        ([300, 200, 60, 20], "fc5fc0", 0.99),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="Astra Live Keyboard fc5fc0",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
    )
    assert res.verified == TriState.TRUE
    assert "visibly confirmed" in res.evidence


def test_verify_text_input_fuzzy_optical_confusion_matching():
    obs_before = make_obs("obs_1", delta_seconds=0)
    obs_after = make_obs("obs_2", delta_seconds=1)
    # Optical confusion: OCR reads '5' as 'S' and '0' as 'O'
    detections = [
        ([260, 270, 300, 25], "Astra Live Keyboard a8OSed", 0.98),
        ([260, 310, 100, 20], "Line 2", 0.95),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="Astra Live Keyboard a805ed",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
        target_bounds=(240, 250, 800, 400),
    )
    assert res.verified == TriState.TRUE
    assert "visibly confirmed" in res.evidence


def test_verify_text_input_cleanup_absence_verification():
    obs_before = make_obs("obs_post", delta_seconds=1)
    obs_after = make_obs("obs_clean", delta_seconds=2)
    # Inside target_bounds, the document buffer is clean (only unrelated UI labels or nothing)
    # Outside target_bounds (e.g. at y=877 in terminal), leftover text might exist, but must be ignored!
    detections = [
        ([277, 877, 250, 20], "Astra Live Keyboard a805ed", 0.99), # Outside target bounds!
        ([250, 150, 80, 20], "File", 0.95),                        # Above target bounds!
        ([260, 280, 10, 15], "|", 0.90),                           # Inside target bounds: empty caret
        ([300, 300, 20, 20], " ", 0.90),
        ([350, 350, 20, 20], " ", 0.90),
        ([400, 400, 20, 20], " ", 0.90),
        ([450, 450, 20, 20], " ", 0.90),
    ]

    res = VerificationEngine.verify_text_input(
        expected_text="Astra Live Keyboard a805ed",
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
        target_bounds=(250, 260, 800, 450), # Correct document bounds [250..1050] x [260..710]
    )
    assert res.verified == TriState.FALSE
    assert res.actual_state == "Text Absent"



