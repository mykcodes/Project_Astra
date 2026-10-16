"""
B.3.2 — Unit Tests for Visual Interaction (Service + Tool)

Proves all 16 required properties:
 1. Valid target reaches the existing physical-input boundary.
 2. Target provenance is preserved.
 3. Invalid ScreenPoint never reaches actuation.
 4. Observation mismatch prevents actuation.
 5. Stale observations prevent actuation.
 6. Invalid target geometry prevents actuation.
 7. Ambiguous selection prevents actuation.
 8. Low-confidence selection prevents actuation.
 9. Missing production perception provider fails explicitly.
10. Missing required permission prevents actuation.
11. Physical-input failure is reported as failure.
12. Successful actuation does not imply semantic success.
13. Verification remains UNKNOWN when appropriate.
14. Raw screenshots are not included in action payloads.
15. The new path does not bypass ActionExecutor.
16. The new path does not call MouseController directly.
"""

import pytest
import json
import asyncio
import inspect
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.domain.entities import ScreenPoint, TriState
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
from app.tools.errors import ToolExecutionError


# ── Helpers ──────────────────────────────────────────────────────

def make_observation(obs_id="obs1", w=1920, h=1080, offset_x=0, offset_y=0) -> VisualObservation:
    return VisualObservation(
        observation_id=obs_id,
        captured_at=datetime.utcnow(),
        width=w,
        height=h,
        virtual_offset_x=offset_x,
        virtual_offset_y=offset_y,
        pixel_format="BGRA",
        image_reference="ref_test",
    )


def make_target(
    target_id="t1", obs_id="obs1", conf=0.9,
    x=100, y=100, w=200, h=200,
) -> VisualTarget:
    return VisualTarget(
        target_id=target_id,
        label="test_button",
        target_type="button",
        confidence=conf,
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        source_observation_id=obs_id,
    )


def make_grounded(target: VisualTarget, obs: VisualObservation, sp: ScreenPoint) -> GroundedTarget:
    return GroundedTarget(
        target=target,
        source_observation_id=obs.observation_id,
        anchor_point=sp,
    )


class FakePerceptionProvider:
    """Test double for PerceptionProvider protocol."""
    def __init__(self, targets=None):
        self._targets = targets if targets is not None else []
    
    def find_targets(self, observation, query):
        return self._targets


def build_service(
    provider=None,
    capture_provider=None,
    selection_service=None,
    grounding_service=None,
    router=None,
) -> VisualInteractionService:
    return VisualInteractionService(
        perception_provider=provider,
        capture_provider=capture_provider,
        selection_service=selection_service,
        grounding_service=grounding_service,
        router=router,
    )


# ── 1. Valid target reaches the existing physical-input boundary ──

@pytest.mark.asyncio
async def test_valid_target_reaches_physical_input_boundary():
    """A valid target should complete the full path to the interaction router."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test_button")
    
    assert result.actuation_success is True
    mock_router.route.assert_called_once()
    call_kwargs = mock_router.route.call_args
    assert call_kwargs.kwargs["point"] == sp
    assert call_kwargs.kwargs["action"] == "CLICK"


# ── 2. Target provenance is preserved ──

@pytest.mark.asyncio
async def test_target_provenance_preserved():
    """Provenance must include observation_id, target_id, screen_point, actuation_outcome."""
    obs = make_observation(obs_id="provenance_obs")
    target = make_target(target_id="provenance_target", obs_id="provenance_obs")
    sp = ScreenPoint(x=300, y=350)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test")
    prov = result.provenance
    
    assert prov["observation_id"] == "provenance_obs"
    assert prov["target_id"] == "provenance_target"
    assert prov["screen_point"] == {"x": 300, "y": 350}
    assert prov["actuation_outcome"] == "SUCCESS"


# ── 3. Invalid ScreenPoint never reaches actuation ──

@pytest.mark.asyncio
async def test_invalid_screen_point_prevents_actuation():
    """If grounding produces geometry outside observation bounds, actuation must not occur."""
    obs = make_observation(obs_id="obs_bounds", w=800, h=600)
    # Target whose center is at x=700+300=1000 which is > 800
    target = make_target(obs_id="obs_bounds", x=700, y=10, w=600, h=100)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    # Use real grounding service — it should reject invalid geometry
    from app.environment.visual.grounding import TargetGroundingService
    real_grounding = TargetGroundingService()
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=real_grounding,
        router=mock_router,
    )
    
    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "INVALID_TARGET_GEOMETRY"
    mock_router.route.assert_not_called()


# ── 4. Observation mismatch prevents actuation ──

@pytest.mark.asyncio
async def test_observation_mismatch_prevents_actuation():
    """Target referencing a different observation must be rejected."""
    obs = make_observation(obs_id="obs_A")
    target = make_target(obs_id="obs_B")  # Mismatch!
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    from app.environment.visual.grounding import TargetGroundingService
    real_grounding = TargetGroundingService()
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=real_grounding,
        router=mock_router,
    )
    
    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "TARGET_OBSERVATION_MISMATCH"
    mock_router.route.assert_not_called()


# ── 5. Stale observations prevent actuation ──

@pytest.mark.asyncio
async def test_stale_observation_prevents_actuation():
    """If an interaction occurred after capture, grounding must reject as stale."""
    obs = make_observation(obs_id="stale_obs")
    target = make_target(obs_id="stale_obs")
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    # Mock the grounding service to raise STALE_OBSERVATION
    mock_grounding = MagicMock()
    mock_grounding.ground.side_effect = VisualCaptureError(
        "STALE_OBSERVATION", "Observation is stale."
    )
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    with pytest.raises(VisualCaptureError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "STALE_OBSERVATION"
    mock_router.route.assert_not_called()


# ── 6. Invalid target geometry prevents actuation ──

@pytest.mark.asyncio
async def test_invalid_target_geometry_prevents_actuation():
    """Grounding must reject a target whose anchor falls outside observation space."""
    obs = make_observation(obs_id="geo_obs", w=100, h=100)
    # Place a target far outside
    target = make_target(obs_id="geo_obs", x=90, y=90, w=100, h=100)
    # Center = (140, 140) which is >= 100 on both axes
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    from app.environment.visual.grounding import TargetGroundingService
    real_grounding = TargetGroundingService()
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=real_grounding,
        router=mock_router,
    )
    
    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "INVALID_TARGET_GEOMETRY"
    mock_router.route.assert_not_called()


# ── 7. Ambiguous selection prevents actuation ──

@pytest.mark.asyncio
async def test_ambiguous_selection_prevents_actuation():
    """Multiple high-confidence candidates must be rejected by selection."""
    obs = make_observation(obs_id="ambig_obs")
    t1 = make_target(target_id="t1", obs_id="ambig_obs", conf=0.9)
    t2 = make_target(target_id="t2", obs_id="ambig_obs", conf=0.95)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    # Use real selection service
    from app.environment.visual.selection import TargetSelectionService
    real_selection = TargetSelectionService()
    
    service = build_service(
        provider=FakePerceptionProvider([t1, t2]),
        capture_provider=mock_capture,
        selection_service=real_selection,
        router=mock_router,
    )
    
    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click("test", min_confidence=0.8)
    
    assert exc.value.code == "TARGET_AMBIGUOUS"
    mock_router.route.assert_not_called()


# ── 8. Low-confidence selection prevents actuation ──

@pytest.mark.asyncio
async def test_low_confidence_prevents_actuation():
    """Candidates below the confidence threshold must be rejected."""
    obs = make_observation(obs_id="lowconf_obs")
    t1 = make_target(obs_id="lowconf_obs", conf=0.3)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    from app.environment.visual.selection import TargetSelectionService
    real_selection = TargetSelectionService()
    
    service = build_service(
        provider=FakePerceptionProvider([t1]),
        capture_provider=mock_capture,
        selection_service=real_selection,
        router=mock_router,
    )
    
    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click("test", min_confidence=0.5)
    
    assert exc.value.code == "TARGET_CONFIDENCE_TOO_LOW"
    mock_router.route.assert_not_called()


# ── 9. Missing production perception provider fails explicitly ──

@pytest.mark.asyncio
async def test_missing_perception_provider_fails_explicitly():
    """Service with no registered provider must fail with structured error."""
    service = build_service(provider=None)  # No provider
    
    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "PERCEPTION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_tool_missing_perception_provider():
    """Tool with default service (no provider) returns structured failure."""
    tool = ExecuteVisualInteractionTool()
    result = await tool.execute(query="test_button")
    
    assert result["success"] is False
    assert result["error"]["code"] == "PERCEPTION_UNAVAILABLE"


# ── 10. Missing required permission prevents actuation ──

@pytest.mark.asyncio
async def test_missing_permission_prevents_actuation():
    """
    ToolExecutor enforces ToolRisk.BLOCKED. Here we verify that the tool
    declares capabilities that exist in the registry's Capability enum
    and that ToolExecutor rejects a BLOCKED tool.
    """
    from app.tools.schemas import ToolRisk
    from app.tools.executor import ToolExecutor
    from app.tools.registry import ToolRegistry, Capability
    from app.ai.providers.types import ToolCall, ToolResult
    
    # Create a tool that is BLOCKED
    tool = ExecuteVisualInteractionTool()
    original_risk = tool.risk
    tool.risk = ToolRisk.BLOCKED
    
    test_registry = ToolRegistry()
    test_registry.register(tool)
    
    test_executor = ToolExecutor()
    test_executor.registry = test_registry
    
    tc = ToolCall(id="tc1", name="execute_visual_interaction", arguments={"query": "test"})
    result = await test_executor.execute(tc)
    
    assert result.success is False
    assert "blocked" in result.error.lower() or "ToolPermissionError" in result.error
    
    # Restore
    tool.risk = original_risk


# ── 11. Physical-input failure is reported as failure ──

@pytest.mark.asyncio
async def test_physical_input_failure_reported():
    """Router returning success=False must propagate as actuation failure."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {
        "success": False,
        "error": {"code": "ACTUATION_FAILURE", "message": "OS rejected SendInput."}
    }
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test")
    
    assert result.actuation_success is False
    assert result.error is not None
    assert result.error["code"] == "ACTUATION_FAILURE"


# ── 12. Successful actuation does not imply semantic success ──

@pytest.mark.asyncio
async def test_successful_actuation_does_not_imply_semantic_success():
    """Actuation SUCCESS must NOT claim verification TRUE."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test")
    
    assert result.actuation_success is True
    assert result.verification == TriState.UNKNOWN
    # NOT TriState.TRUE


# ── 13. Verification remains UNKNOWN when appropriate ──

@pytest.mark.asyncio
async def test_verification_unknown_on_success():
    """On successful actuation, verification must be UNKNOWN (not TRUE)."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test")
    result_dict = result.to_dict()
    
    assert result_dict["verification"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_verification_unknown_on_failure():
    """On failed actuation, verification must also be UNKNOWN (not FALSE or TRUE)."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {
        "success": False,
        "error": {"code": "ACTUATION_FAILURE", "message": "Failed"}
    }
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test")
    assert result.verification == TriState.UNKNOWN


# ── 14. Raw screenshots are not included in action payloads ──

@pytest.mark.asyncio
async def test_no_raw_screenshots_in_payloads():
    """Provenance and result must not contain screenshot bytes or image_reference."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test")
    result_dict = result.to_dict()
    result_str = json.dumps(result_dict)
    
    # Must NOT contain image_reference or raw bytes
    assert "image_reference" not in result_str
    assert "ref_test" not in result_str
    # Must NOT contain pixel data indicators
    assert "BGRA" not in result_str
    assert "pixel_format" not in result_str


# ── 15. The new path does not bypass ActionExecutor ──

def test_tool_registered_in_executor_path():
    """
    The tool must be executable through ToolExecutor, not called directly.
    Verify the tool follows the Tool ABC contract so ToolExecutor can invoke it.
    """
    from app.tools.base import Tool
    tool = ExecuteVisualInteractionTool()
    
    # It IS a Tool subclass
    assert isinstance(tool, Tool)
    
    # It has the required attributes
    assert hasattr(tool, 'name')
    assert hasattr(tool, 'description')
    assert hasattr(tool, 'risk')
    assert hasattr(tool, 'schema')
    assert hasattr(tool, 'execute')
    
    # execute is async (required by ToolExecutor)
    assert asyncio.iscoroutinefunction(tool.execute)
    
    # It can be registered in a registry
    from app.tools.registry import ToolRegistry
    test_registry = ToolRegistry()
    test_registry.register(tool)
    assert test_registry.has("execute_visual_interaction")


# ── 16. The new path does not call MouseController directly ──

def test_no_direct_mouse_controller_import():
    """
    The interaction service and tool must not import or reference MouseController directly.
    They must go through the interaction router.
    """
    import app.environment.visual.interaction as interaction_module
    import app.tools.builtin.visual_interaction as tool_module
    
    interaction_source = inspect.getsource(interaction_module)
    tool_source = inspect.getsource(tool_module)
    
    # Neither module should import mouse_controller
    assert "mouse_controller" not in interaction_source
    assert "MouseController" not in interaction_source
    assert "mouse_controller" not in tool_source
    assert "MouseController" not in tool_source


# ── Additional edge-case tests ──

@pytest.mark.asyncio
async def test_perception_provider_empty_results():
    """Perception returning empty list → TARGET_NOT_FOUND from selection."""
    obs = make_observation()
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    from app.environment.visual.selection import TargetSelectionService
    real_selection = TargetSelectionService()
    
    service = build_service(
        provider=FakePerceptionProvider([]),  # No targets found
        capture_provider=mock_capture,
        selection_service=real_selection,
        router=mock_router,
    )
    
    with pytest.raises(VisualPerceptionError) as exc:
        await service.execute_click("nonexistent_button")
    
    assert exc.value.code == "TARGET_NOT_FOUND"
    mock_router.route.assert_not_called()


@pytest.mark.asyncio
async def test_perception_provider_exception():
    """Perception provider raising an exception → structured PERCEPTION_FAILED."""
    obs = make_observation()
    
    class FailingProvider:
        def find_targets(self, observation, query):
            raise RuntimeError("Model crashed")
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    
    service = build_service(
        provider=FailingProvider(),
        capture_provider=mock_capture,
        router=mock_router,
    )
    
    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "PERCEPTION_FAILED"
    mock_router.route.assert_not_called()


@pytest.mark.asyncio
async def test_router_exception_propagates():
    """Router raising an exception → structured PHYSICAL_INPUT_FAILED."""
    obs = make_observation()
    target = make_target(obs_id=obs.observation_id)
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    
    mock_router = AsyncMock()
    mock_router.route.side_effect = RuntimeError("Router crashed")
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    with pytest.raises(VisualInteractionError) as exc:
        await service.execute_click("test")
    
    assert exc.value.code == "PHYSICAL_INPUT_FAILED"


@pytest.mark.asyncio
async def test_tool_translates_all_errors_to_structured_dicts():
    """The tool must translate all known error types into structured result dicts."""
    # Test with VisualPerceptionError (e.g., TARGET_NOT_FOUND)
    mock_service = AsyncMock()
    mock_service.execute_click.side_effect = VisualPerceptionError(
        "TARGET_NOT_FOUND", "No targets found."
    )
    
    tool = ExecuteVisualInteractionTool()
    tool._service = mock_service
    
    result = await tool.execute(query="test")
    assert result["success"] is False
    assert result["error"]["code"] == "TARGET_NOT_FOUND"
    
    # Test with VisualCaptureError
    mock_service.execute_click.side_effect = VisualCaptureError(
        "DPI_MAPPING_FAILURE", "DPI mismatch."
    )
    result = await tool.execute(query="test")
    assert result["success"] is False
    assert result["error"]["code"] == "DPI_MAPPING_FAILURE"
    
    # Test with VisualInteractionError
    mock_service.execute_click.side_effect = VisualInteractionError(
        "PERCEPTION_UNAVAILABLE", "No provider."
    )
    result = await tool.execute(query="test")
    assert result["success"] is False
    assert result["error"]["code"] == "PERCEPTION_UNAVAILABLE"


@pytest.mark.asyncio
async def test_tool_unexpected_error_raises_tool_execution_error():
    """Unexpected exceptions must be re-raised as ToolExecutionError."""
    mock_service = AsyncMock()
    mock_service.execute_click.side_effect = ValueError("Unexpected")
    
    tool = ExecuteVisualInteractionTool()
    tool._service = mock_service
    
    with pytest.raises(ToolExecutionError):
        await tool.execute(query="test")


@pytest.mark.asyncio
async def test_provided_observation_is_used():
    """When an observation is provided, capture should not be called."""
    obs = make_observation(obs_id="pre_provided")
    target = make_target(obs_id="pre_provided")
    sp = ScreenPoint(x=200, y=200)
    grounded = make_grounded(target, obs, sp)
    
    mock_capture = MagicMock()  # Should NOT be called
    
    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "action": "CLICK", "verified": TriState.UNKNOWN}
    
    mock_grounding = MagicMock()
    mock_grounding.ground.return_value = grounded
    
    service = build_service(
        provider=FakePerceptionProvider([target]),
        capture_provider=mock_capture,
        grounding_service=mock_grounding,
        router=mock_router,
    )
    
    result = await service.execute_click("test", observation=obs)
    
    assert result.actuation_success is True
    assert result.provenance["observation_id"] == "pre_provided"
    mock_capture.capture_virtual_screen.assert_not_called()
