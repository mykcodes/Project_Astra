"""
B.3.2 — Live Test for Visual Interaction

Uses:
- Real B.2 screenshot capture (ScreenCaptureProvider)
- A test-only explicitly injected controlled PerceptionProvider
- Real B.3.1 selection (TargetSelectionService)
- Real B.3.1 grounding (TargetGroundingService)
- Real B.2 coordinate mapping (VisualCoordinateMapper)
- The existing B.1 actuation boundary (InteractionRouter → MouseController)

The test provider forges a target with known geometry in the center
of the screen. It does NOT claim to recognize an actual UI element.

The test does NOT click an uncontrolled UI element — the forged target
is in the center of the virtual screen, which is a known safe coordinate.

Reports the actual actuation outcome:
- If Windows accepts it → actuation SUCCESS, verification UNKNOWN
- If Windows rejects it → structured ACTUATION_FAILURE

Does NOT weaken B.1 to accommodate environmental restrictions.
"""

import pytest
from typing import List

from app.domain.entities import TriState
from app.domain.visual import VisualObservation, VisualTarget
from app.environment.visual.capture import screen_capture_provider
from app.environment.visual.interaction import VisualInteractionService, VisualInteractionError
from app.environment.visual.grounding import target_grounding_service
from app.environment.visual.selection import target_selection_service


class ControlledTestPerceptionProvider:
    """
    Test-only perception provider that forges a single controlled target
    at a known geometry relative to the observation.

    Does NOT claim to recognize any real UI element.
    Does NOT fabricate confidence artificially.
    """

    def find_targets(self, observation: VisualObservation, query: str) -> List[VisualTarget]:
        """
        Returns a single forged target centered in the observation space.
        This is a 100x100 box placed at the center of the captured image.
        """
        box_width = 100
        box_height = 100
        box_x = (observation.width - box_width) // 2
        box_y = (observation.height - box_height) // 2

        return [
            VisualTarget(
                target_id="live_test_controlled_target",
                label="controlled_test_box",
                target_type="test",
                confidence=1.0,
                bbox_x=box_x,
                bbox_y=box_y,
                bbox_width=box_width,
                bbox_height=box_height,
                source_observation_id=observation.observation_id,
            )
        ]


@pytest.mark.asyncio
async def test_live_visual_interaction_end_to_end():
    """
    Live end-to-end test of the B.3.2 visual interaction pipeline.

    Path:
        VisualInteractionService.execute_click()
            → real ScreenCaptureProvider.capture_virtual_screen()
            → ControlledTestPerceptionProvider.find_targets()
            → real TargetSelectionService.select_target()
            → real TargetGroundingService.ground()
                → real VisualCoordinateMapper.map_to_screen_point()
                    → real InteractionTracker freshness check
            → real InteractionRouter.route(CLICK, point=ScreenPoint)
                → real MouseController.actuate_click()
    """
    # Inject the controlled test perception provider
    test_provider = ControlledTestPerceptionProvider()

    service = VisualInteractionService(
        perception_provider=test_provider,
        capture_provider=screen_capture_provider,
        selection_service=target_selection_service,
        grounding_service=target_grounding_service,
        # Uses real interaction_router by default
    )

    result = await service.execute_click(
        query="controlled_test_box",
        min_confidence=0.5,
    )

    # ── Provenance assertions ──
    prov = result.provenance

    assert "observation_id" in prov, "Provenance must include observation_id"
    assert "target_id" in prov, "Provenance must include target_id"
    assert prov["target_id"] == "live_test_controlled_target"
    assert "screen_point" in prov, "Provenance must include screen_point"
    assert isinstance(prov["screen_point"]["x"], int)
    assert isinstance(prov["screen_point"]["y"], int)
    assert "actuation_outcome" in prov

    # ── Actuation outcome ──
    # The outcome depends on the runtime environment.
    # In an interactive desktop session, SendInput should succeed.
    # In a headless/CI environment, it may fail.
    # We report the actual result without assuming either.

    if result.actuation_success:
        # OS accepted the physical input
        assert prov["actuation_outcome"] == "SUCCESS"
        # Verification must be UNKNOWN — we cannot confirm the click hit anything meaningful
        assert result.verification == TriState.UNKNOWN
        assert result.error is None
        print(f"LIVE TEST: Actuation SUCCEEDED at ({prov['screen_point']['x']}, {prov['screen_point']['y']})")
    else:
        # OS rejected the physical input (e.g., UIPI, headless session)
        assert prov["actuation_outcome"] == "FAILURE"
        assert result.error is not None
        print(f"LIVE TEST: Actuation FAILED — {result.error}")

    # ── Verification must always be UNKNOWN ──
    assert result.verification == TriState.UNKNOWN

    # ── No raw screenshot data in result ──
    result_dict = result.to_dict()
    import json
    result_str = json.dumps(result_dict)
    assert "image_reference" not in result_str
    assert "pixel_format" not in result_str
