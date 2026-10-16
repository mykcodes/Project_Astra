import pytest
from datetime import datetime
from pydantic import ValidationError

from app.domain.visual import VisualTarget, VisualObservation, VisualPerceptionError, VisualCaptureError
from app.environment.visual.selection import target_selection_service
from app.environment.visual.grounding import target_grounding_service
from app.environment.visual.mapper import visual_mapper
from app.domain.entities import ScreenPoint

def create_mock_obs(observation_id: str, w=1920, h=1080) -> VisualObservation:
    return VisualObservation(
        observation_id=observation_id,
        captured_at=datetime.utcnow(),
        width=w,
        height=h,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref123"
    )

def create_target(target_id="t1", obs_id="obs1", conf=0.9, x=10, y=10, w=100, h=100) -> VisualTarget:
    return VisualTarget(
        target_id=target_id,
        label="button",
        target_type="ui",
        confidence=conf,
        bbox_x=x,
        bbox_y=y,
        bbox_width=w,
        bbox_height=h,
        source_observation_id=obs_id
    )

def test_visual_target_validation():
    # Valid
    vt = create_target()
    assert vt.confidence == 0.9
    
    # Invalid confidence
    with pytest.raises(ValidationError):
        create_target(conf=1.5)
        
    with pytest.raises(ValidationError):
        create_target(conf=-0.1)
        
    # Invalid geometry
    with pytest.raises(ValidationError):
        create_target(w=0)
        
    with pytest.raises(ValidationError):
        create_target(x=-5)

def test_selection_empty_candidates():
    with pytest.raises(VisualPerceptionError) as exc:
        target_selection_service.select_target([])
    assert exc.value.code == "TARGET_NOT_FOUND"

def test_selection_low_confidence():
    t1 = create_target(conf=0.4)
    with pytest.raises(VisualPerceptionError) as exc:
        target_selection_service.select_target([t1], min_confidence=0.5)
    assert exc.value.code == "TARGET_CONFIDENCE_TOO_LOW"

def test_selection_ambiguity():
    t1 = create_target(target_id="t1", conf=0.9)
    t2 = create_target(target_id="t2", conf=0.95)
    with pytest.raises(VisualPerceptionError) as exc:
        target_selection_service.select_target([t1, t2], min_confidence=0.8)
    assert exc.value.code == "TARGET_AMBIGUOUS"

def test_selection_success():
    t1 = create_target(conf=0.9)
    selected = target_selection_service.select_target([t1], min_confidence=0.8)
    assert selected.target_id == "t1"

def test_grounding_provenance_mismatch():
    obs = create_mock_obs("obs1")
    t1 = create_target(obs_id="obs2")
    with pytest.raises(VisualPerceptionError) as exc:
        target_grounding_service.ground(t1, obs)
    assert exc.value.code == "TARGET_OBSERVATION_MISMATCH"

def test_grounding_invalid_geometry():
    obs = create_mock_obs("obs1", w=800, h=600)
    # Bbox whose center is at x = 700 + 300 = 1000 (outside 800)
    t1 = create_target(obs_id="obs1", x=700, y=10, w=600, h=100)
    with pytest.raises(VisualPerceptionError) as exc:
        target_grounding_service.ground(t1, obs)
    assert exc.value.code == "INVALID_TARGET_GEOMETRY"

def test_grounding_success(monkeypatch):
    obs = create_mock_obs("obs1", w=1920, h=1080)
    obs.virtual_offset_x = 100
    obs.virtual_offset_y = 50
    t1 = create_target(obs_id="obs1", x=100, y=100, w=200, h=200)
    
    # Center should be x=200, y=200
    # Map to screen point should be x=300, y=250
    
    # We must ensure interaction_tracker doesn't fail us. In a pure unit test we can just mock mapper 
    # OR we can just let mapper run if we mock the tracker. Mapper is lightweight.
    from app.environment.visual.tracker import interaction_tracker
    monkeypatch.setattr(interaction_tracker, "get_last_interaction", lambda: datetime.min)
    
    gt = target_grounding_service.ground(t1, obs)
    assert gt.target.target_id == "t1"
    assert gt.source_observation_id == "obs1"
    assert gt.anchor_point.x == 300
    assert gt.anchor_point.y == 250

def test_grounding_stale_observation(monkeypatch):
    obs = create_mock_obs("obs1")
    t1 = create_target(obs_id="obs1")
    
    def mock_map(*args, **kwargs):
        raise VisualCaptureError("STALE_OBSERVATION", "Stale")
        
    monkeypatch.setattr(visual_mapper, "map_to_screen_point", mock_map)
    
    with pytest.raises(VisualCaptureError) as exc:
        target_grounding_service.ground(t1, obs)
    assert exc.value.code == "STALE_OBSERVATION"
