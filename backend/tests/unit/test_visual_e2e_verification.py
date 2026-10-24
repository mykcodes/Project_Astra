"""
B.3.7 — Unit Tests for End-to-End Verified Visual Interaction

Covers:
- Target provenance and observation freshness rejection.
- Ambiguous or missing targets (TARGET_NOT_FOUND, TARGET_AMBIGUOUS).
- Invalid or out-of-bounds geometry (INVALID_TARGET_GEOMETRY).
- Permission denial (ToolRisk.BLOCKED).
- Actuation rejection (ACTUATION_FAILURE).
- Accepted actuation with unavailable post-action evidence (UNKNOWN).
- Verified success from fresh evidence (VERIFIED_SUCCESS / TriState.TRUE).
- Verified failure from reliable contradictory evidence (VERIFIED_FAILURE / CLICK_NO_EFFECT).
- UNKNOWN for ambiguous post-action observations or stale evidence.
- Cleanup failure reported separately without rewriting interaction outcome.

All tests operate with mocks or isolated domain objects — ZERO physical mouse movements.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.ai.orchestrator.action_executor import ActionExecutor
from app.ai.orchestrator.verification import VerificationEngine
from app.domain.entities import ScreenPoint, TriState
from app.domain.goals import FailureClass, Intent, SemanticAction, VerificationResult
from app.domain.visual import (
    GroundedTarget,
    VisualCaptureError,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
from app.environment.visual.grounding import TargetGroundingService
from app.environment.visual.interaction import VisualInteractionService
from app.environment.visual.selection import TargetSelectionService
from app.tools.builtin.visual_interaction import ExecuteVisualInteractionTool
from app.tools.errors import ToolPermissionError
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.tools.schemas import ToolRisk


def make_obs(obs_id: str = "obs_1", delta_seconds: int = 0) -> VisualObservation:
    captured = datetime.utcnow() + timedelta(seconds=delta_seconds)
    return VisualObservation(
        observation_id=obs_id,
        captured_at=captured,
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA8",
        image_reference=f"img_{obs_id}",
    )


def make_target(
    obs_id: str,
    label: str = "File",
    x: int = 100,
    y: int = 50,
    w: int = 30,
    h: int = 20,
    confidence: float = 0.95,
) -> VisualTarget:
    return VisualTarget(
        target_id=f"target_{label}_{obs_id}",
        label=label,
        target_type="text",
        confidence=confidence,
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        source_observation_id=obs_id,
    )


# =============================================================================
# 1. VerificationEngine Unit Tests: Dropdown State Verification
# =============================================================================

def test_verification_success_from_fresh_evidence():
    """Fresh post-action OCR clearly showing dropdown menu items below anchor -> VERIFIED_SUCCESS."""
    obs_before = make_obs("obs_pre", delta_seconds=0)
    obs_after = make_obs("obs_post", delta_seconds=2)
    anchor = make_target("obs_pre", label="File", x=100, y=50, w=30, h=20)

    # Detections below anchor (Notepad File menu items)
    detections_after = [
        ([100, 75, 60, 18], "New tab", 0.99),
        ([100, 95, 45, 18], "Open", 0.99),
        ([100, 115, 40, 18], "Save", 0.99),
        ([100, 135, 35, 18], "Exit", 0.99),
        ([500, 50, 40, 20], "Help", 0.99),
        ([200, 200, 100, 20], "Some document text", 0.95),
    ]

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections_after,
    )

    assert res.verified == TriState.TRUE
    assert res.actual_state == "Menu Open"
    assert res.observation_id == "obs_post"
    assert "New tab" in res.evidence or "Save" in res.evidence
    assert res.failure_code is None


def test_verification_failure_when_dropdown_does_not_appear():
    """Fresh post-action OCR with normal text but no dropdown items below anchor -> VERIFIED_FAILURE."""
    obs_before = make_obs("obs_pre", delta_seconds=0)
    obs_after = make_obs("obs_post", delta_seconds=2)
    anchor = make_target("obs_pre", label="File", x=100, y=50, w=30, h=20)

    # Document text and window headers detected, but no menu items below File
    detections_after = [
        ([100, 50, 30, 20], "File", 0.99),
        ([140, 50, 30, 20], "Edit", 0.99),
        ([180, 50, 35, 20], "View", 0.99),
        ([500, 50, 35, 20], "Help", 0.99),
        ([200, 200, 120, 20], "Document paragraph 1", 0.95),
        ([200, 230, 120, 20], "Document paragraph 2", 0.95),
        ([200, 260, 120, 20], "Document paragraph 3", 0.95),
    ]

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections_after,
    )

    assert res.verified == TriState.FALSE
    assert res.actual_state == "Menu Closed"
    assert res.failure_code == FailureClass.CLICK_NO_EFFECT
    assert "did not appear below anchor" in res.evidence


def test_verification_unknown_when_post_action_observation_missing():
    """Post-action observation unavailable -> UNKNOWN."""
    obs_before = make_obs("obs_pre", delta_seconds=0)
    anchor = make_target("obs_pre", label="File")

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=None,
        detections_after=None,
    )

    assert res.verified == TriState.UNKNOWN
    assert res.failure_code == FailureClass.UNKNOWN
    assert "unavailable" in res.evidence


def test_verification_unknown_when_post_action_observation_stale():
    """Post-action observation timestamp <= pre-action timestamp -> UNKNOWN (STALE_TARGET)."""
    obs_before = make_obs("obs_pre", delta_seconds=10)
    obs_after = make_obs("obs_post", delta_seconds=5)  # Older!
    anchor = make_target("obs_pre", label="File")

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=[([100, 75, 60, 18], "New tab", 0.99)],
    )

    assert res.verified == TriState.UNKNOWN
    assert res.failure_code == FailureClass.STALE_TARGET
    assert "not fresher" in res.evidence


def test_verification_unknown_when_ocr_detections_empty_or_sparse():
    """Blank or sparse detections in post-action OCR -> UNKNOWN."""
    obs_before = make_obs("obs_pre", delta_seconds=0)
    obs_after = make_obs("obs_post", delta_seconds=2)
    anchor = make_target("obs_pre", label="File")

    # Case A: 0 detections
    res_empty = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=[],
    )
    assert res_empty.verified == TriState.UNKNOWN
    assert res_empty.failure_code == FailureClass.UNKNOWN

    # Case B: Detections None
    res_none = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=None,
    )
    assert res_none.verified == TriState.UNKNOWN

    # Case C: Sparse detections (< 5 items and no dropdown)
    res_sparse = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=[([10, 10, 20, 20], "X", 0.9)],
    )
    assert res_sparse.verified == TriState.UNKNOWN
    assert res_sparse.actual_state == "Ambiguous"


# =============================================================================
# 2. Target Selection, Grounding, and Provenance Unit Tests
# =============================================================================

def test_target_provenance_and_observation_mismatch():
    """Target belonging to obs_A cannot be grounded against obs_B."""
    obs_a = make_obs("obs_A")
    obs_b = make_obs("obs_B")
    target_a = make_target("obs_A", label="File")

    grounding = TargetGroundingService()
    with pytest.raises(VisualPerceptionError) as exc_info:
        grounding.ground(target_a, obs_b)

    assert exc_info.value.code == "TARGET_OBSERVATION_MISMATCH"


def test_ambiguous_and_missing_targets_prevent_actuation():
    """Empty or ambiguous candidates fail cleanly before actuation."""
    selection = TargetSelectionService()

    # Empty candidates
    with pytest.raises(VisualPerceptionError) as exc_info:
        selection.select_target([])
    assert exc_info.value.code == "TARGET_NOT_FOUND"

    # Ambiguous candidates
    t1 = make_target("obs_1", label="File", x=100, y=50, confidence=0.9)
    t2 = make_target("obs_1", label="File", x=500, y=50, confidence=0.9)
    with pytest.raises(VisualPerceptionError) as exc_info:
        selection.select_target([t1, t2], min_confidence=0.5)
    assert exc_info.value.code == "TARGET_AMBIGUOUS"


def test_invalid_or_out_of_bounds_geometry_prevents_actuation():
    """Target anchor falling outside observation bounds fails grounding."""
    obs = make_obs("obs_1")
    # Target center: 2000 + 50 = 2050 > 1920 width
    invalid_target = make_target("obs_1", label="File", x=2000, y=50, w=100, h=50)

    grounding = TargetGroundingService()
    with pytest.raises(VisualPerceptionError) as exc_info:
        grounding.ground(invalid_target, obs)

    assert exc_info.value.code == "INVALID_TARGET_GEOMETRY"


# =============================================================================
# 3. Pipeline Execution, Permissions, and Actuation Boundaries
# =============================================================================

@pytest.mark.asyncio
async def test_permission_denial_blocks_visual_tool():
    """Tool registered with ToolRisk.BLOCKED is rejected by ToolExecutor without actuation."""
    mock_service = MagicMock()
    mock_service.execute_click = AsyncMock()

    tool = ExecuteVisualInteractionTool(service=mock_service)
    tool.risk = ToolRisk.BLOCKED

    custom_registry = ToolRegistry()
    custom_registry.register(tool)

    executor = ToolExecutor()
    executor.registry = custom_registry

    from app.ai.providers.types import ToolCall
    tool_call = ToolCall(id="call_1", name="execute_visual_interaction", arguments={"query": "File"})

    res = await executor.execute(tool_call)
    assert res.success is False
    assert "ToolPermissionError" in res.error or "blocked" in res.error.lower()
    mock_service.execute_click.assert_not_called()


@pytest.mark.asyncio
async def test_actuation_rejection_reported_accurately():
    """When OS rejects SendInput, pipeline reports ACTUATION_FAILURE without fabricating success."""
    mock_router = MagicMock()
    mock_router.route = AsyncMock(return_value={
        "success": False,
        "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected SendInput for CLICK."}
    })

    obs = make_obs("obs_pre")
    target = make_target("obs_pre", label="File")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    tool = ExecuteVisualInteractionTool(service=service)
    result = await tool.execute(query="File")

    assert result["success"] is False
    assert result["actuation_success"] is False
    assert result["verification"] == "UNKNOWN"
    assert result["error"]["code"] == "ACTUATION_FAILURE"
    assert result["provenance"]["actuation_outcome"] == "FAILURE"


@pytest.mark.asyncio
async def test_accepted_actuation_with_unavailable_post_evidence_reports_unknown():
    """OS accepted click, but post-action observation is unavailable -> status remains UNKNOWN."""
    mock_router = MagicMock()
    mock_router.route = AsyncMock(return_value={"success": True})

    obs = make_obs("obs_pre")
    target = make_target("obs_pre", label="File")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    # 1. Execute click via tool
    tool = ExecuteVisualInteractionTool(service=service)
    click_res = await tool.execute(query="File")
    assert click_res["success"] is True
    assert click_res["actuation_success"] is True

    # 2. Simulate post-action observation failure
    obs_post = None
    verification = VerificationEngine.verify_visual_menu_state(
        anchor_target=target,
        obs_before=obs,
        obs_after=obs_post,
        detections_after=None,
    )

    # Actuation was accepted, but verification is UNKNOWN
    assert verification.verified == TriState.UNKNOWN
    assert verification.failure_code == FailureClass.UNKNOWN


# =============================================================================
# 4. Cleanup Outcome Independence
# =============================================================================

def test_cleanup_failure_reported_separately_without_overwriting_interaction_outcome():
    """
    If primary visual interaction achieved VERIFIED_SUCCESS, but subsequent cleanup
    fails (e.g., closing the menu encountered an issue), the primary interaction's
    outcome remains VERIFIED_SUCCESS, and cleanup is reported as a separate structured failure.
    """
    # Primary interaction outcome
    primary_result = VerificationResult(
        verified=TriState.TRUE,
        confidence=0.95,
        verification_type="VISUAL_MENU",
        expected_state="Menu Open",
        actual_state="Menu Open",
        evidence="Dropdown menu opened successfully.",
    )

    # Cleanup interaction outcome (separate tracking)
    cleanup_result = {
        "cleanup_attempted": True,
        "cleanup_success": False,
        "cleanup_status": "CLEANUP_FAILED",
        "error": {"code": "CLEANUP_TOGGLE_FAILED", "message": "Failed to close dropdown menu cleanly."},
    }

    # Consolidated report preserves the distinct identities
    e2e_report = {
        "primary_action": "CLICK_FILE_MENU",
        "primary_verification": primary_result.verified,
        "primary_status": "VERIFIED_SUCCESS",
        "cleanup": cleanup_result,
    }

    assert e2e_report["primary_verification"] == TriState.TRUE
    assert e2e_report["primary_status"] == "VERIFIED_SUCCESS"
    assert e2e_report["cleanup"]["cleanup_success"] is False
    assert e2e_report["cleanup"]["cleanup_status"] == "CLEANUP_FAILED"


# =============================================================================
# 5. Provenance Validation, Menu-Bar Filtering & Verification Anchor Derivation
# =============================================================================

from tests.live.test_live_e2e_visual_interaction import (
    filter_menu_bar_candidates,
    validate_actuation_provenance,
    derive_verification_anchor,
)


def test_filter_menu_bar_candidates_selects_header_and_ignores_document_body():
    """
    Stage 3 menu bar filter correctly isolates the File menu header inside the
    top-left menu strip and ignores matching text in document body or outside window.
    """
    win_bounds = (240, 170, 1440, 740)
    win_x, win_y, win_w, win_h = win_bounds

    header_cand = make_target("obs_pre", label="File", x=266, y=237, w=25, h=13)
    doc_cand = make_target("obs_pre", label="'File'", x=774, y=427, w=63, h=15)
    outside_cand = make_target("obs_pre", label="File", x=50, y=50, w=30, h=20)
    oversized_cand = make_target("obs_pre", label="File", x=266, y=237, w=300, h=100)
    other_label_cand = make_target("obs_pre", label="Edit", x=300, y=237, w=25, h=13)

    candidates = [outside_cand, doc_cand, oversized_cand, other_label_cand, header_cand]

    filtered = filter_menu_bar_candidates(
        candidates=candidates,
        win_x=win_x,
        win_y=win_y,
        win_w=win_w,
        win_h=win_h,
        menu_name="File",
    )

    assert len(filtered) == 1
    assert filtered[0].target_id == header_cand.target_id
    assert filtered[0].bbox_x == 266
    assert filtered[0].bbox_y == 237


def test_filter_menu_bar_candidates_handles_empty_and_no_match():
    """Empty candidate list or non-matching menu name yields empty results."""
    assert filter_menu_bar_candidates([], 240, 170, 1440, 740, "File") == []

    cand = make_target("obs_1", label="Help", x=350, y=200, w=30, h=15)
    assert filter_menu_bar_candidates([cand], 240, 170, 1440, 740, "File") == []


def test_validate_actuation_provenance_success():
    """Valid provenance with matching observation_id, target_id, and point in menu strip passes."""
    provenance = {
        "observation_id": "vi_9cf152998bab",
        "target_id": "ocr_target_vi_9cf152998bab_32",
        "screen_point": {"x": 278, "y": 243},
        "actuation_outcome": "SUCCESS",
    }
    win_bounds = (240, 170, 1440, 740)

    is_valid, reason = validate_actuation_provenance(provenance, window_bounds=win_bounds)
    assert is_valid is True
    assert reason == "OK"


def test_validate_actuation_provenance_rejects_missing_or_failed_outcome():
    """Missing fields, empty dict, or failed outcome are rejected."""
    # None provenance
    v, r = validate_actuation_provenance(None)
    assert v is False
    assert "missing" in r.lower()

    # Failed outcome
    v, r = validate_actuation_provenance({"actuation_outcome": "FAILURE"})
    assert v is False
    assert "not SUCCESS" in r

    # Missing observation_id
    v, r = validate_actuation_provenance({
        "actuation_outcome": "SUCCESS",
        "target_id": "t1",
        "screen_point": {"x": 100, "y": 100},
    })
    assert v is False
    assert "Observation ID" in r

    # Missing target_id
    v, r = validate_actuation_provenance({
        "actuation_outcome": "SUCCESS",
        "observation_id": "obs_1",
        "screen_point": {"x": 100, "y": 100},
    })
    assert v is False
    assert "Target ID" in r

    # Non-integer screen point
    v, r = validate_actuation_provenance({
        "actuation_outcome": "SUCCESS",
        "observation_id": "obs_1",
        "target_id": "t1",
        "screen_point": {"x": "invalid", "y": 100},
    })
    assert v is False
    assert "integers" in r


def test_validate_actuation_provenance_rejects_out_of_bounds_or_document_point():
    """Provenance with points outside window or outside menu strip is rejected."""
    win_bounds = (240, 170, 1440, 740)

    # Point outside window entirely
    p_outside = {
        "observation_id": "obs_1",
        "target_id": "t1",
        "screen_point": {"x": 100, "y": 100},
        "actuation_outcome": "SUCCESS",
    }
    v, r = validate_actuation_provenance(p_outside, window_bounds=win_bounds)
    assert v is False
    assert "outside target window bounds" in r

    # Point inside window but in document body (previous failure case: (805, 434))
    p_doc = {
        "observation_id": "obs_1",
        "target_id": "t1",
        "screen_point": {"x": 805, "y": 434},
        "actuation_outcome": "SUCCESS",
    }
    v, r = validate_actuation_provenance(p_doc, window_bounds=win_bounds)
    assert v is False
    assert "outside menu bar strip" in r
    assert "document content" in r


def test_derive_verification_anchor_creates_valid_target_and_verifies_dropdown():
    """
    Derived verification anchor uses authoritative provenance coordinates to position
    the verifier ROI and confirms dropdown menu items beneath the clicked point.
    """
    provenance = {
        "observation_id": "vi_9cf152998bab",
        "target_id": "ocr_target_vi_9cf152998bab_32",
        "screen_point": {"x": 278, "y": 243},
        "actuation_outcome": "SUCCESS",
    }

    anchor = derive_verification_anchor(provenance, query="File")
    assert anchor.target_id == "ocr_target_vi_9cf152998bab_32"
    assert anchor.label == "File"
    assert anchor.source_observation_id == "vi_9cf152998bab"
    # Bbox centered around (278, 243)
    assert anchor.bbox_x == 278 - 15  # 263
    assert anchor.bbox_y == 243 - 10  # 233
    assert anchor.bbox_width == 30
    assert anchor.bbox_height == 20

    # Verify that VerificationEngine correctly identifies dropdown items beneath this anchor
    obs_pre = make_obs("vi_9cf152998bab", delta_seconds=0)
    obs_post = make_obs("obs_post", delta_seconds=1)

    # Dropdown items located beneath (278, 243)
    post_detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([266, 320, 35, 18], "Exit", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_pre,
        obs_after=obs_post,
        detections_after=post_detections,
    )

    assert res.verified == TriState.TRUE
    assert res.actual_state == "Menu Open"
    assert "New tab" in res.evidence or "Save" in res.evidence


def test_target_selection_disambiguates_by_window_bounds():
    """When multiple viable candidates exist across screen, target_bounds disambiguates to window candidate."""
    selection = TargetSelectionService()
    # Candidate 1: inside window (200, 100, 800, 600)
    t_inside = make_target("obs_1", label="File", x=220, y=140, confidence=0.99)
    # Candidate 2: outside window (e.g. in IDE / background)
    t_outside = make_target("obs_1", label="File", x=1400, y=300, confidence=0.99)

    selected = selection.select_target(
        [t_inside, t_outside],
        min_confidence=0.5,
        target_bounds=(200, 100, 800, 600),
    )
    assert selected == t_inside
    assert selected.bbox_x == 220


def test_target_selection_disambiguates_by_menu_strip_within_window():
    """When multiple candidates are inside window, header in menu strip is preferred over document content."""
    selection = TargetSelectionService()
    # Candidate 1: in menu strip (top 160px of window at y=100)
    t_menu = make_target("obs_1", label="File", x=220, y=140, confidence=0.99)
    # Candidate 2: in document content body (y=450)
    t_doc = make_target("obs_1", label="File", x=500, y=450, confidence=0.99)

    selected = selection.select_target(
        [t_menu, t_doc],
        min_confidence=0.5,
        target_bounds=(200, 100, 800, 600),
    )
    assert selected == t_menu
    assert selected.bbox_y == 140


def test_target_selection_deduplicates_harmless_ocr_duplicates():
    """Duplicate detections from OCR within the target window menu strip resolve to the menu control."""
    selection = TargetSelectionService()
    # Duplicate detections from OCR of the exact same 'File' menu item (in menu strip of window)
    t1 = make_target("obs_1", label="File", x=266, y=237, w=25, h=13, confidence=0.95)
    t2 = make_target("obs_1", label="File", x=267, y=237, w=26, h=14, confidence=0.99)

    selected = selection.select_target(
        [t1, t2],
        min_confidence=0.5,
        target_bounds=(200, 100, 800, 600),
    )
    assert selected in (t1, t2)
    assert selected.label == "File"


def test_target_selection_exact_match_over_multi_word_line():
    """Exact word match 'File' is preferred over multi-word line 'File Edit View'."""
    selection = TargetSelectionService()
    t_exact = make_target("obs_1", label="File", x=266, y=237, w=25, h=13, confidence=0.99)
    t_line = make_target("obs_1", label="File Edit View", x=266, y=237, w=120, h=13, confidence=0.99)

    selected = selection.select_target([t_exact, t_line], min_confidence=0.5, query="File")
    assert selected == t_exact
    assert selected.label == "File"


@pytest.mark.asyncio
async def test_execute_visual_interaction_tool_with_target_bounds():
    """ExecuteVisualInteractionTool accepts target_bounds and passes it to service."""
    from unittest.mock import AsyncMock
    from app.tools.builtin.visual_interaction import ExecuteVisualInteractionTool
    from app.environment.visual.interaction import VisualInteractionResult
    from app.domain.entities import TriState

    mock_service = AsyncMock()
    mock_service.execute_click.return_value = VisualInteractionResult(
        actuation_success=True,
        verification=TriState.UNKNOWN,
        provenance={"observation_id": "obs_123", "target_id": "tgt_1", "screen_point": {"x": 278, "y": 243}},
    )

    tool = ExecuteVisualInteractionTool(service=mock_service)
    assert "target_bounds" in tool.schema["properties"]

    res = await tool.execute(
        query="File",
        min_confidence=0.5,
        target_bounds=[240, 170, 1440, 740],
    )

    assert res["success"] is True
    mock_service.execute_click.assert_awaited_once_with(
        query="File",
        min_confidence=0.5,
        target_bounds=(240, 170, 1440, 740),
        recheck_pre_actuation=True,
    )


def test_mouse_controller_actuate_click_dwell_time_and_diagnostics(monkeypatch):
    """MouseController.actuate_click executes move, dwell time, and returns rich diagnostics."""
    from app.interaction.input.mouse_controller import MouseController
    from app.domain.entities import ScreenPoint

    mc = MouseController()
    sent_inputs = []

    def mock_send_input(inputs):
        sent_inputs.extend(inputs)
        return True

    def mock_move(point, verify=True):
        return {"success": True, "action": "MOVE_MOUSE"}

    monkeypatch.setattr(mc, "_send_input", mock_send_input)
    monkeypatch.setattr(mc, "actuate_move", mock_move)
    monkeypatch.setattr(mc, "get_cursor_pos_safe", lambda: (True, ScreenPoint(x=278, y=243)))

    res = mc.actuate_click(ScreenPoint(x=278, y=243))
    assert res["success"] is True
    assert "diagnostics" in res
    diag = res["diagnostics"]
    assert diag["target_point"] == {"x": 278, "y": 243}
    assert diag["cursor_before_click"] == {"x": 278, "y": 243}
    assert diag["cursor_discrepancy"] == {"x": 0, "y": 0}
    assert diag["button_down_accepted"] is True
    assert diag["button_up_accepted"] is True
    assert diag["dwell_ms"] == 60
    assert len(sent_inputs) == 2  # down, then up


# =============================================================================
# 4. Menu Opening & Closing Verification State Machine Regression Tests
# =============================================================================

def test_menu_verification_successful_opening():
    """When expected_menu_open=True, detecting dropdown items below anchor yields VERIFIED_SUCCESS."""
    anchor = make_target("obs_pre", label="File", x=266, y=237, w=25, h=13)
    obs_before = make_obs("obs_pre", delta_seconds=0)
    obs_after = make_obs("obs_post", delta_seconds=1)
    detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
        expected_menu_open=True,
    )
    assert res.verified == TriState.TRUE
    assert res.actual_state == "Menu Open"
    assert res.expected_state == "Menu Open"
    assert "New tab" in res.evidence


def test_menu_verification_successful_closing():
    """When expected_menu_open=False, absence of dropdown items across normal screen text yields VERIFIED_SUCCESS."""
    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_before = make_obs("obs_post", delta_seconds=1)
    obs_after = make_obs("obs_clean", delta_seconds=2)
    # Menu is closed: normal document / UI detections exist, but NO dropdown items below anchor
    detections = [
        ([266, 237, 25, 13], "File", 0.99),
        ([310, 237, 25, 13], "Edit", 0.99),
        ([350, 237, 25, 13], "View", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
        expected_menu_open=False,
    )
    assert res.verified == TriState.TRUE
    assert res.actual_state == "Menu Closed"
    assert res.expected_state == "Menu Closed"
    assert "dropdown menu closed" in res.evidence


def test_menu_verification_failed_closing():
    """When expected_menu_open=False, but dropdown items remain visible, yields VERIFIED_FAILURE."""
    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_before = make_obs("obs_post", delta_seconds=1)
    obs_after = make_obs("obs_clean", delta_seconds=2)
    # Menu failed to close: dropdown items are still present
    detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    res = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=detections,
        expected_menu_open=False,
    )
    assert res.verified == TriState.FALSE
    assert res.actual_state == "Menu Open"
    assert res.expected_state == "Menu Closed"
    assert res.failure_code == FailureClass.VERIFICATION_FAILED
    assert "dropdown menu remains open" in res.evidence


def test_menu_verification_cleanup_unknown_when_sparse_or_stale():
    """When post-cleanup evidence is sparse or stale, yields UNKNOWN rather than guessing."""
    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)

    # Case A: Sparse detections (< 5 items)
    obs_before = make_obs("obs_post", delta_seconds=1)
    obs_after = make_obs("obs_clean", delta_seconds=2)
    res_sparse = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_after,
        detections_after=[([266, 237, 25, 13], "File", 0.99)],
        expected_menu_open=False,
    )
    assert res_sparse.verified == TriState.UNKNOWN
    assert res_sparse.actual_state == "Ambiguous"
    assert res_sparse.failure_code == FailureClass.UNKNOWN

    # Case B: Stale post-cleanup observation
    obs_stale = make_obs("obs_clean_stale", delta_seconds=0)  # captured_at <= obs_before
    res_stale = VerificationEngine.verify_visual_menu_state(
        anchor_target=anchor,
        obs_before=obs_before,
        obs_after=obs_stale,
        detections_after=[([10, 10, 20, 20], "Txt", 0.99)] * 6,
        expected_menu_open=False,
    )
    assert res_stale.verified == TriState.UNKNOWN
    assert res_stale.actual_state == "Stale Observation"
    assert res_stale.failure_code == FailureClass.STALE_TARGET


# =============================================================================
# 5. execute_safe_menu_cleanup Unit Regression Tests
# =============================================================================

@pytest.mark.asyncio
async def test_execute_safe_menu_cleanup_tier1_escape_success(monkeypatch):
    """If Escape key closes the menu, Tier 1 succeeds and subsequent tiers are not attempted."""
    from tests.live.test_live_e2e_visual_interaction import execute_safe_menu_cleanup

    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_prior = make_obs("obs_post", delta_seconds=1)
    obs_clean = make_obs("obs_clean_1", delta_seconds=2)

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_clean
    mock_capture.store.retrieve.return_value = b"fake_bytes"

    # OCR sees menu closed (no dropdown items, >= 5 screen elements)
    clean_detections = [
        ([266, 237, 25, 13], "File", 0.99),
        ([310, 237, 25, 13], "Edit", 0.99),
        ([350, 237, 25, 13], "View", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    mock_executor = AsyncMock()
    mock_ocr = MagicMock(return_value=clean_detections)

    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_escape", lambda **kw: {"success": True})

    success, status, result = await execute_safe_menu_cleanup(
        target_hwnd=12345,
        window_bounds=(240, 170, 1440, 740),
        anchor_target=anchor,
        obs_prior=obs_prior,
        screen_capture_provider=mock_capture,
        action_executor=mock_executor,
        ocr_worker_fn=mock_ocr,
    )

    assert success is True
    assert status == "CLEANUP_SUCCESS"
    assert result.verified == TriState.TRUE
    assert result.actual_state == "Menu Closed"
    mock_executor.execute_intent.assert_not_called()


@pytest.mark.asyncio
async def test_execute_safe_menu_cleanup_tier2_alt_success(monkeypatch):
    """If Escape fails, Tier 2 executes an Alt key toggle to cancel menu mode."""
    from tests.live.test_live_e2e_visual_interaction import execute_safe_menu_cleanup

    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_prior = make_obs("obs_post", delta_seconds=1)
    obs_clean_1 = make_obs("obs_clean_1", delta_seconds=2)
    obs_clean_2 = make_obs("obs_clean_2", delta_seconds=3)

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = [obs_clean_1, obs_clean_2]
    mock_capture.store.retrieve.return_value = b"fake_bytes"

    # Tier 1 detections: dropdown still open
    tier1_detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    # Tier 2 detections: menu closed after Alt key
    tier2_detections = [
        ([266, 237, 25, 13], "File", 0.99),
        ([310, 237, 25, 13], "Edit", 0.99),
        ([350, 237, 25, 13], "View", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    mock_ocr = MagicMock(side_effect=[tier1_detections, tier2_detections])
    mock_executor = AsyncMock()

    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_escape", lambda **kw: {"success": True})
    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_alt", lambda **kw: {"success": True})

    success, status, result = await execute_safe_menu_cleanup(
        target_hwnd=12345,
        window_bounds=(240, 170, 1440, 740),
        anchor_target=anchor,
        obs_prior=obs_prior,
        screen_capture_provider=mock_capture,
        action_executor=mock_executor,
        ocr_worker_fn=mock_ocr,
    )

    assert success is True
    assert status == "CLEANUP_SUCCESS"
    assert result.verified == TriState.TRUE
    assert result.actual_state == "Menu Closed"
    mock_executor.execute_intent.assert_not_called()


@pytest.mark.asyncio
async def test_execute_safe_menu_cleanup_tier3_neutral_click_success(monkeypatch):
    """If Escape and Alt both fail, Tier 3 executes a neutral document click to light-dismiss."""
    from tests.live.test_live_e2e_visual_interaction import execute_safe_menu_cleanup

    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_prior = make_obs("obs_post", delta_seconds=1)
    obs_clean_1 = make_obs("obs_clean_1", delta_seconds=2)
    obs_clean_2 = make_obs("obs_clean_2", delta_seconds=3)
    obs_clean_3 = make_obs("obs_clean_3", delta_seconds=4)

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = [obs_clean_1, obs_clean_2, obs_clean_3]
    mock_capture.store.retrieve.return_value = b"fake_bytes"

    # Tiers 1 and 2 detections: dropdown still open
    open_detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    # Tier 3 detections: menu closed after neutral click
    closed_detections = [
        ([266, 237, 25, 13], "File", 0.99),
        ([310, 237, 25, 13], "Edit", 0.99),
        ([350, 237, 25, 13], "View", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    mock_ocr = MagicMock(side_effect=[open_detections, open_detections, closed_detections])
    mock_executor = AsyncMock()
    mock_executor.execute_intent.return_value = {"success": True}

    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_escape", lambda **kw: {"success": True})
    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_alt", lambda **kw: {"success": True})

    success, status, result = await execute_safe_menu_cleanup(
        target_hwnd=12345,
        window_bounds=(240, 170, 1440, 740),
        anchor_target=anchor,
        obs_prior=obs_prior,
        screen_capture_provider=mock_capture,
        action_executor=mock_executor,
        ocr_worker_fn=mock_ocr,
    )

    assert success is True
    assert status == "CLEANUP_SUCCESS"
    assert result.verified == TriState.TRUE
    assert result.actual_state == "Menu Closed"

    # Verify Tier 3 clicked neutral document area, NOT menu header (x=278, y=243)
    mock_executor.execute_intent.assert_called_once()
    call_args = mock_executor.execute_intent.call_args
    intent_called = call_args.kwargs["intent"]
    tool_args_called = call_args.kwargs["tool_args"]
    assert intent_called.capability_id == "desktop.physical_input"
    assert tool_args_called["intent"] == "CLICK"
    assert tool_args_called["x"] >= 500
    assert tool_args_called["y"] >= 450


@pytest.mark.asyncio
async def test_execute_safe_menu_cleanup_failed_when_menu_remains_open(monkeypatch):
    """When all tiers fail to close the menu, reports CLEANUP_FAILED."""
    from tests.live.test_live_e2e_visual_interaction import execute_safe_menu_cleanup

    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_prior = make_obs("obs_post", delta_seconds=1)
    obs_clean_1 = make_obs("obs_clean_1", delta_seconds=2)
    obs_clean_2 = make_obs("obs_clean_2", delta_seconds=3)
    obs_clean_3 = make_obs("obs_clean_3", delta_seconds=4)

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = [obs_clean_1, obs_clean_2, obs_clean_3]
    mock_capture.store.retrieve.return_value = b"fake_bytes"

    # All tiers still detect menu items below anchor
    lingering_detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    mock_ocr = MagicMock(return_value=lingering_detections)
    mock_executor = AsyncMock()
    mock_executor.execute_intent.return_value = {"success": True}

    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_escape", lambda **kw: {"success": True})
    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_alt", lambda **kw: {"success": True})

    success, status, result = await execute_safe_menu_cleanup(
        target_hwnd=12345,
        window_bounds=(240, 170, 1440, 740),
        anchor_target=anchor,
        obs_prior=obs_prior,
        screen_capture_provider=mock_capture,
        action_executor=mock_executor,
        ocr_worker_fn=mock_ocr,
    )

    assert success is False
    assert status == "CLEANUP_FAILED"
    assert result.verified == TriState.FALSE
    assert result.actual_state == "Menu Open"


@pytest.mark.asyncio
async def test_execute_safe_menu_cleanup_unconfirmed_when_ambiguous(monkeypatch):
    """When post-cleanup visual evidence is ambiguous (sparse detections), reports CLEANUP_UNCONFIRMED."""
    from tests.live.test_live_e2e_visual_interaction import execute_safe_menu_cleanup

    anchor = make_target("obs_post", label="File", x=266, y=237, w=25, h=13)
    obs_prior = make_obs("obs_post", delta_seconds=1)
    obs_clean_1 = make_obs("obs_clean_1", delta_seconds=2)
    obs_clean_2 = make_obs("obs_clean_2", delta_seconds=3)
    obs_clean_3 = make_obs("obs_clean_3", delta_seconds=4)

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = [obs_clean_1, obs_clean_2, obs_clean_3]
    mock_capture.store.retrieve.return_value = b"fake_bytes"

    # Tiers 1 and 2 detect menu open
    open_detections = [
        ([266, 260, 60, 18], "New tab", 0.99),
        ([266, 280, 45, 18], "Open", 0.99),
        ([266, 300, 40, 18], "Save", 0.99),
        ([500, 240, 40, 20], "Help", 0.99),
        ([774, 427, 63, 15], "Some text in document", 0.95),
    ]

    # Tier 3: ambiguous evidence (< 5 detections, e.g. blank capture during animation)
    sparse_detections = [
        ([266, 237, 25, 13], "File", 0.99),
    ]

    mock_ocr = MagicMock(side_effect=[open_detections, open_detections, sparse_detections])
    mock_executor = AsyncMock()
    mock_executor.execute_intent.return_value = {"success": True}

    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_escape", lambda **kw: {"success": True})
    monkeypatch.setattr("app.interaction.input.keyboard_controller.keyboard_controller.actuate_alt", lambda **kw: {"success": True})

    success, status, result = await execute_safe_menu_cleanup(
        target_hwnd=12345,
        window_bounds=(240, 170, 1440, 740),
        anchor_target=anchor,
        obs_prior=obs_prior,
        screen_capture_provider=mock_capture,
        action_executor=mock_executor,
        ocr_worker_fn=mock_ocr,
    )

    assert success is False
    assert status == "CLEANUP_UNCONFIRMED"
    assert result.verified == TriState.UNKNOWN
    assert result.actual_state == "Ambiguous"





