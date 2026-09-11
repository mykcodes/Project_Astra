import pytest
from datetime import datetime, timedelta
from app.domain.visual import VisualObservation, VisualCaptureError
from app.environment.visual.mapper import visual_mapper
from app.environment.visual.tracker import interaction_tracker
from app.domain.entities import ScreenPoint

def test_coordinate_mapping_invariant():
    """
    Proves that ImagePixel(x, y) maps to ScreenPoint(x + virtual_offset_x, y + virtual_offset_y).
    Tests with a negative virtual offset (monitor to the left).
    """
    obs = VisualObservation(
        observation_id="test_obs",
        captured_at=datetime.utcnow(),
        width=3840,
        height=1080,
        virtual_offset_x=-1920,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="img_123"
    )
    
    # Ensure interaction tracker doesn't invalidate it
    interaction_tracker._last_interaction = obs.captured_at - timedelta(seconds=1)
    
    # 1. Top left pixel (0,0) -> (-1920, 0)
    point = visual_mapper.map_to_screen_point(obs, 0, 0)
    assert point.x == -1920
    assert point.y == 0
    
    # 2. Pixel on right monitor (2000, 100) -> (80, 100)
    point = visual_mapper.map_to_screen_point(obs, 2000, 100)
    assert point.x == 80
    assert point.y == 100

def test_stale_observation_invalidation():
    """
    Proves that if an interaction occurs after capture, the observation is stale.
    """
    obs = VisualObservation(
        observation_id="test_obs",
        captured_at=datetime.utcnow() - timedelta(seconds=2),
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="img_123"
    )
    
    # Interaction happens 1 second AFTER capture
    interaction_tracker._last_interaction = obs.captured_at + timedelta(seconds=1)
    
    with pytest.raises(VisualCaptureError) as exc:
        visual_mapper.map_to_screen_point(obs, 100, 100)
        
    assert exc.value.code == "STALE_OBSERVATION"
