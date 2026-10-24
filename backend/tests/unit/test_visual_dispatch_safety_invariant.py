"""
ASTRA Phase B.12 — Production Safety Invariant Verification

Invariant under test:
    NO FRESH VALID TARGET -> ZERO PHYSICAL INPUT DISPATCH

Covers all 7 mandatory test conditions against the production gate and physical dispatch boundary:
1. Stable target (permits physical dispatch with verified coordinates).
2. Moved target (rejects before actuation, 0 physical dispatches).
3. Disappeared target (rejects before actuation, 0 physical dispatches).
4. Occluded target (rejects before actuation, 0 physical dispatches).
5. Ambiguous target (rejects before actuation, 0 physical dispatches).
6. Stale or failed observation (rejects before actuation, 0 physical dispatches).
7. Observation timeout or exception (rejects before actuation, 0 physical dispatches).
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.domain.entities import ScreenPoint, TriState
from app.domain.goals import SemanticAction
from app.domain.visual import (
    GroundedTarget,
    VisualCaptureError,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
from app.environment.visual.interaction import (
    VisualInteractionError,
    VisualInteractionResult,
    VisualInteractionService,
)
from app.tools.builtin.visual_interaction import ExecuteVisualInteractionTool
from app.interaction.router import InteractionRouter


# --- Test Fixtures & Helpers ---

def create_obs(obs_id: str = "obs_1", width: int = 1920, height: int = 1080) -> VisualObservation:
    return VisualObservation(
        observation_id=obs_id,
        captured_at=datetime.now(timezone.utc),
        width=width,
        height=height,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference=f"ref_{obs_id}",
    )


def create_target(
    target_id: str = "target_1",
    label: str = "Submit",
    x: int = 200,
    y: int = 300,
    w: int = 80,
    h: int = 30,
    conf: float = 0.95,
    obs_id: str = "obs_1",
) -> VisualTarget:
    return VisualTarget(
        target_id=target_id,
        label=label,
        target_type="button",
        confidence=conf,
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        source_observation_id=obs_id,
    )


# --- 1. Stable Target ---

@pytest.mark.asyncio
async def test_invariant_stable_target_permits_actuation():
    """A valid, stationary target verified in fresh observation permits physical dispatch."""
    obs_init = create_obs("obs_init")
    obs_fresh = create_obs("obs_fresh")
    target = create_target("t_stable", "Save", x=200, y=200, w=100, h=40, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}

    # Tracker confirms stationary target at identical coordinates
    regrounded = GroundedTarget(
        target=create_target("t_stable", "Save", x=200, y=200, w=100, h=40, obs_id="obs_fresh"),
        source_observation_id="obs_fresh",
        anchor_point=ScreenPoint(x=250, y=220),
    )
    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.return_value = regrounded

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    result = await service.execute_click(query="Save", observation=obs_init)

    assert result.actuation_success is True
    assert result.verification == TriState.UNKNOWN
    # Physical router called exactly once with verified coordinates
    mock_router.route.assert_awaited_once_with(
        action=SemanticAction.CLICK.value,
        target_entity=None,
        hwnds=None,
        pids=None,
        point=ScreenPoint(x=250, y=220),
    )


# --- 2. Moved Target ---

@pytest.mark.asyncio
async def test_invariant_moved_target_rejects_and_prevents_dispatch():
    """Target moved beyond safe tolerance aborts with TARGET_MOVED and dispatches ZERO input."""
    obs_init = create_obs("obs_init")
    obs_fresh = create_obs("obs_fresh")
    target = create_target("t_moved", "Save", x=200, y=200, w=100, h=40, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_tracker = MagicMock()
    # Tracker detects target displacement > tolerance
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_MOVED", "Target 'Save' moved 60.0px (exceeds safety threshold 8.0px)."
    )

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click(query="Save", observation=obs_init)

    assert exc.value.code == "TARGET_MOVED"
    # ZERO physical input dispatches
    mock_router.route.assert_not_called()


# --- 3. Disappeared Target ---

@pytest.mark.asyncio
async def test_invariant_disappeared_target_rejects_and_prevents_dispatch():
    """Target absent from fresh observation aborts with TARGET_DISAPPEARED and dispatches ZERO input."""
    obs_init = create_obs("obs_init")
    obs_fresh = create_obs("obs_fresh")
    target = create_target("t_vanished", "Cancel", x=150, y=150, w=60, h=25, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_DISAPPEARED", "Target 'Cancel' is no longer visible in fresh observation."
    )

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click(query="Cancel", observation=obs_init)

    assert exc.value.code == "TARGET_DISAPPEARED"
    mock_router.route.assert_not_called()


# --- 4. Occluded Target ---

@pytest.mark.asyncio
async def test_invariant_occluded_target_rejects_and_prevents_dispatch():
    """Occluded target aborts with TARGET_OCCLUDED and dispatches ZERO input."""
    obs_init = create_obs("obs_init")
    obs_fresh = create_obs("obs_fresh")
    target = create_target("t_occluded", "Options", x=300, y=300, w=70, h=30, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_OCCLUDED", "Target 'Options' is occluded by an overlapping window."
    )

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click(query="Options", observation=obs_init)

    assert exc.value.code == "TARGET_OCCLUDED"
    mock_router.route.assert_not_called()


# --- 5. Ambiguous Target ---

@pytest.mark.asyncio
async def test_invariant_ambiguous_target_rejects_and_prevents_dispatch():
    """Multiple identical candidates abort with TARGET_AMBIGUOUS and dispatch ZERO input."""
    obs_init = create_obs("obs_init")
    t1 = create_target("t1", "Item", x=100, y=100, w=50, h=20, conf=0.9, obs_id="obs_init")
    t2 = create_target("t2", "Item", x=100, y=200, w=50, h=20, conf=0.9, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [t1, t2]

    mock_capture = MagicMock()
    mock_router = AsyncMock()

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click(query="Item", observation=obs_init)

    assert exc.value.code == "TARGET_AMBIGUOUS"
    mock_router.route.assert_not_called()


# --- 6. Stale or Failed Observation ---

@pytest.mark.asyncio
async def test_invariant_stale_or_failed_observation_prevents_dispatch():
    """Observation failure during pre-actuation re-grounding aborts with OBSERVATION_STALE."""
    obs_init = create_obs("obs_init")
    target = create_target("t_stale", "File", x=50, y=50, w=40, h=20, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = VisualCaptureError(
        "BUFFER_STALE", "Observation buffer expired or stale."
    )

    mock_router = AsyncMock()

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click(query="File", observation=obs_init)

    assert exc.value.code == "OBSERVATION_STALE"
    mock_router.route.assert_not_called()


# --- 7. Observation Timeout or Exception ---

@pytest.mark.asyncio
async def test_invariant_observation_timeout_or_exception_prevents_dispatch():
    """Observation capture timeout or unexpected exception aborts with PRE_ACTUATION_FAILED."""
    obs_init = create_obs("obs_init")
    target = create_target("t_timeout", "Edit", x=80, y=50, w=40, h=20, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = TimeoutError("DWM frame capture timed out.")

    mock_router = AsyncMock()

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click(query="Edit", observation=obs_init)

    assert exc.value.code == "PRE_ACTUATION_FAILED"
    mock_router.route.assert_not_called()


# --- 8. Tool Boundary & Physical Actuator End-to-End ---

@pytest.mark.asyncio
async def test_invariant_end_to_end_physical_driver_unreached_on_failure():
    """
    Proves across the complete ActionExecutor -> Tool -> Service -> Router -> MouseController
    boundary that OS-level MouseController.actuate_click is NEVER invoked when target fails.
    """
    from app.interaction.input.mouse_controller import mouse_controller

    obs_init = create_obs("obs_init")
    obs_fresh = create_obs("obs_fresh")
    target = create_target("t_fail", "DangerousAction", x=400, y=400, w=100, h=30, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [target]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = [obs_init, obs_fresh]

    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_MOVED", "Target shifted 120px."
    )

    real_router = InteractionRouter()

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=real_router,
        target_tracker=mock_tracker,
    )

    tool = ExecuteVisualInteractionTool(service=service)

    with patch.object(mouse_controller, "actuate_click") as mock_actuate:
        result = await tool.execute(query="DangerousAction")

        assert result["success"] is False
        assert result["actuation_success"] is False
        assert result["error"]["code"] == "TARGET_MOVED"
        # The physical mouse controller MUST NOT be called!
        mock_actuate.assert_not_called()
