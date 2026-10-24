from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.domain.entities import ScreenPoint, TriState
from app.domain.visual import (
    GroundedTarget,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
from app.environment.visual.interaction import VisualInteractionService, VisualInteractionError
from app.environment.visual.tracking import SpatialTargetTracker
from app.domain.goals import SemanticAction


def make_obs(obs_id="obs_test"):
    return VisualObservation(
        observation_id=obs_id,
        captured_at=datetime.now(timezone.utc),
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref1",
    )


def make_target(target_id="target_1", label="Save", x=100, y=100, w=60, h=30, obs_id="obs_test"):
    return VisualTarget(
        target_id=target_id,
        label=label,
        target_type="text",
        confidence=0.95,
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        source_observation_id=obs_id,
    )


def test_tracker_stable_target():
    tracker = SpatialTargetTracker(default_drift_tolerance_px=8.0)
    obs1 = make_obs("obs_1")
    obs2 = make_obs("obs_2")
    t1 = make_target("t1", "Save", x=100, y=100, w=60, h=30, obs_id="obs_1")

    # In obs2, target is at identical coordinates
    cand = make_target("t_cand", "Save", x=100, y=100, w=60, h=30, obs_id="obs_2")
    tracked = tracker.track_in_observation(t1, obs2, candidates=[cand])

    assert tracked.is_stale is False
    assert tracked.movement_px == 0.0
    assert tracked.current_bbox.x == 100
    assert tracked.current_bbox.y == 100


def test_tracker_small_displacement_within_tolerance():
    tracker = SpatialTargetTracker(default_drift_tolerance_px=8.0)
    obs1 = make_obs("obs_1")
    obs2 = make_obs("obs_2")
    t1 = make_target("t1", "Save", x=100, y=100, w=60, h=30, obs_id="obs_1")

    # In obs2, target moved 3px right and 4px down (Euclidean distance = 5px)
    cand = make_target("t_cand", "Save", x=103, y=104, w=60, h=30, obs_id="obs_2")
    tracked = tracker.track_in_observation(t1, obs2, candidates=[cand])

    assert tracked.is_stale is False
    assert 4.9 <= tracked.movement_px <= 5.1

    grounded = GroundedTarget(
        target=t1,
        source_observation_id="obs_1",
        anchor_point=ScreenPoint(x=130, y=115),
    )
    re_grounded = tracker.re_ground_pre_actuation(grounded, obs2, candidates=[cand])
    assert re_grounded.source_observation_id == "obs_2"
    # New anchor point should reflect the 3px/4px shift
    assert re_grounded.anchor_point.x == 133
    assert re_grounded.anchor_point.y == 119


def test_tracker_disappeared_target_raises_error():
    tracker = SpatialTargetTracker()
    obs1 = make_obs("obs_1")
    obs2 = make_obs("obs_2")
    t1 = make_target("t1", "Cancel", x=200, y=200, w=50, h=25, obs_id="obs_1")

    # obs2 has candidates but none matching "Cancel"
    cand = make_target("t_cand", "Other", x=200, y=200, w=50, h=25, obs_id="obs_2")
    tracked = tracker.track_in_observation(t1, obs2, candidates=[cand])
    assert tracked.is_stale is True

    grounded = GroundedTarget(
        target=t1,
        source_observation_id="obs_1",
        anchor_point=ScreenPoint(x=225, y=212),
    )
    with pytest.raises(VisualPerceptionError) as exc_info:
        tracker.re_ground_pre_actuation(grounded, obs2, candidates=[cand])
    assert exc_info.value.code == "TARGET_DISAPPEARED"


def test_tracker_excessive_movement_raises_target_moved():
    tracker = SpatialTargetTracker(default_drift_tolerance_px=5.0, max_trackable_drift_px=25.0)
    obs1 = make_obs("obs_1")
    obs2 = make_obs("obs_2")
    t1 = make_target("t1", "Submit", x=50, y=50, w=80, h=30, obs_id="obs_1")

    # Shift by 40px (> max_trackable_drift_px 25.0)
    cand = make_target("t_cand", "Submit", x=90, y=50, w=80, h=30, obs_id="obs_2")

    grounded = GroundedTarget(
        target=t1,
        source_observation_id="obs_1",
        anchor_point=ScreenPoint(x=90, y=65),
    )
    with pytest.raises(VisualPerceptionError) as exc_info:
        tracker.re_ground_pre_actuation(grounded, obs2, candidates=[cand])
    # Beyond max trackable drift, target is classified as disappeared / moved outside tracking range
    assert exc_info.value.code in ("TARGET_MOVED", "TARGET_DISAPPEARED")


@pytest.mark.asyncio
async def test_interaction_service_pre_actuation_rejection_prevents_physical_dispatch():
    obs_initial = make_obs("obs_init")
    obs_fresh = make_obs("obs_fresh")
    t1 = make_target("t1", "Confirm", x=300, y=300, w=70, h=30, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [t1]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_tracker = MagicMock()
    # Tracker raises TARGET_DISAPPEARED during pre-actuation validation
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_DISAPPEARED", "Target disappeared from screen."
    )

    mock_observer = MagicMock()

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
        observer=mock_observer,
    )

    with pytest.raises(VisualInteractionError) as exc_info:
        await service.execute_click(
            query="Confirm",
            observation=obs_initial,
        )

    assert exc_info.value.code == "TARGET_DISAPPEARED"
    # Physical router MUST NEVER have been invoked!
    mock_router.route.assert_not_called()


@pytest.mark.asyncio
async def test_interaction_service_moved_target_rejection():
    """Target moved beyond tolerance must be rejected before physical input."""
    obs_initial = make_obs("obs_init")
    obs_fresh = make_obs("obs_fresh")
    t1 = make_target("t1", "Save", x=100, y=100, w=50, h=25, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [t1]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_MOVED", "Target moved 45.0px (exceeds safety threshold)."
    )

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    with pytest.raises(VisualInteractionError) as exc_info:
        await service.execute_click(query="Save", observation=obs_initial)

    assert exc_info.value.code == "TARGET_MOVED"
    mock_router.route.assert_not_called()


@pytest.mark.asyncio
async def test_interaction_service_occluded_target_rejection():
    """Occluded target must be rejected before physical input."""
    obs_initial = make_obs("obs_init")
    obs_fresh = make_obs("obs_fresh")
    t1 = make_target("t1", "Save", x=100, y=100, w=50, h=25, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [t1]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.side_effect = VisualPerceptionError(
        "TARGET_OCCLUDED", "Target is occluded by overlapping window."
    )

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    with pytest.raises(VisualInteractionError) as exc_info:
        await service.execute_click(query="Save", observation=obs_initial)

    assert exc_info.value.code == "TARGET_OCCLUDED"
    mock_router.route.assert_not_called()


@pytest.mark.asyncio
async def test_interaction_service_fresh_regrounding_updates_coordinates():
    """Freshly re-grounded target must dispatch clicks using updated coordinates."""
    obs_initial = make_obs("obs_init")
    obs_fresh = make_obs("obs_fresh")
    t1 = make_target("t1", "Save", x=100, y=100, w=60, h=30, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [t1]

    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs_fresh

    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}

    # Simulate target shifting 5px right and 5px down
    regrounded_target = GroundedTarget(
        target=make_target("t1", "Save", x=105, y=105, w=60, h=30, obs_id="obs_fresh"),
        source_observation_id="obs_fresh",
        anchor_point=ScreenPoint(x=135, y=120),
    )
    mock_tracker = MagicMock()
    mock_tracker.re_ground_pre_actuation.return_value = regrounded_target

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
        target_tracker=mock_tracker,
    )

    result = await service.execute_click(query="Save", observation=obs_initial)
    assert result.actuation_success is True
    # Router must be called with the updated anchor point (135, 120), NOT the old point!
    mock_router.route.assert_awaited_once_with(
        action=SemanticAction.CLICK.value,
        target_entity=None,
        hwnds=None,
        pids=None,
        point=ScreenPoint(x=135, y=120),
    )


@pytest.mark.asyncio
async def test_interaction_service_capture_failure_fails_closed():
    """Observation capture failure during pre-actuation must fail closed with zero physical input."""
    obs_initial = make_obs("obs_init")
    t1 = make_target("t1", "Save", x=100, y=100, w=60, h=30, obs_id="obs_init")

    mock_provider = MagicMock()
    mock_provider.find_targets.return_value = [t1]

    mock_capture = MagicMock()
    # Pre-actuation capture fails
    from app.domain.visual import VisualCaptureError
    mock_capture.capture_virtual_screen.side_effect = VisualCaptureError(
        "IMAGE_EXPIRED", "Underlying DXcam capture buffer expired."
    )

    mock_router = AsyncMock()

    service = VisualInteractionService(
        perception_provider=mock_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    with pytest.raises(VisualInteractionError) as exc_info:
        await service.execute_click(query="Save", observation=obs_initial)

    assert exc_info.value.code == "OBSERVATION_STALE"
    mock_router.route.assert_not_called()
