import pytest
import asyncio
from datetime import datetime

from app.environment.visual.capture import screen_capture_provider
from app.environment.visual.grounding import target_grounding_service
from app.domain.visual import VisualTarget
from app.domain.entities import ScreenPoint

@pytest.mark.asyncio
async def test_live_b3_visual_perception_foundation():
    """
    Live test proving B.3.1 foundations against a real B.2 screen capture.
    This test strictly DOES NOT actuate the mouse and DOES NOT claim visual recognition.
    It mathematically validates the target grounding boundaries.
    """
    # 1. Capture a real B.2 observation
    obs = screen_capture_provider.capture_virtual_screen("live_b3_test")
    
    assert obs.width > 0
    assert obs.height > 0
    
    # 2. Forge a controlled VisualTarget (TEST INPUT ONLY)
    # We place a 100x100 box in the center of the image space
    box_width = 100
    box_height = 100
    box_x = (obs.width - box_width) // 2
    box_y = (obs.height - box_height) // 2
    
    target = VisualTarget(
        target_id="test_target_1",
        label="controlled_test_box",
        target_type="test",
        confidence=1.0,
        bbox_x=box_x,
        bbox_y=box_y,
        bbox_width=box_width,
        bbox_height=box_height,
        source_observation_id=obs.observation_id
    )
    
    # 3. Ground the target
    grounded = target_grounding_service.ground(target, obs)
    
    # 4. Verify results
    assert grounded.source_observation_id == obs.observation_id
    
    # Expected anchor is center of the box, mapped to physical space
    expected_image_x = box_x + box_width // 2
    expected_image_y = box_y + box_height // 2
    
    expected_physical_x = expected_image_x + obs.virtual_offset_x
    expected_physical_y = expected_image_y + obs.virtual_offset_y
    
    assert grounded.anchor_point.x == expected_physical_x
    assert grounded.anchor_point.y == expected_physical_y
    
    # 5. ZERO actuation occurs. The test successfully mapped a semantic 
    # image-space target to a physical OS coordinate securely!
