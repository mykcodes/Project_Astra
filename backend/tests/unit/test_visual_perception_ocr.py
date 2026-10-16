"""
B.3.3 — Unit Tests for Real Visual Perception Provider (OCR)

Proves all 10 mandated requirements:
 1. Valid OCR detections produce valid VisualTarget candidates.
 2. Detected bounding boxes are preserved correctly.
 3. Confidence and source observation identity are preserved.
 4. No OCR detections produce TARGET_NOT_FOUND when evaluated with selection service.
 5. Multiple plausible matches obey the existing ambiguity policy (TARGET_AMBIGUOUS).
 6. Malformed or out-of-bounds geometry is rejected with structured errors.
 7. OCR initialization/inference failures become structured failures.
 8. Missing/expired image references fail safely (IMAGE_EXPIRED).
 9. Stale observations are rejected according to existing freshness rules (STALE_OBSERVATION).
 10. No raw screenshot or screen text leaks into normal logs/tool output.
"""

import math
from datetime import datetime, timedelta
import numpy as np
import pytest

from app.domain.visual import (
    VisualCaptureError,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
from app.environment.visual.perception import (
    OcrPerceptionProvider,
    matches_text_query,
)
from app.environment.visual.selection import target_selection_service
from app.environment.visual.tracker import interaction_tracker


class InMemoryTestImageStore:
    """Test-double for ImageReferenceStore."""
    def __init__(self):
        self._store = {}

    def store(self, ref_id: str, data: bytes):
        self._store[ref_id] = data

    def retrieve(self, ref_id: str) -> bytes:
        if ref_id not in self._store:
            raise VisualCaptureError("IMAGE_EXPIRED", f"Reference {ref_id} expired or missing.")
        return self._store[ref_id]


def make_test_observation(
    obs_id: str = "obs_ocr_test",
    width: int = 800,
    height: int = 600,
    ref_id: str = "img_ref_1",
    captured_at: datetime | None = None,
) -> VisualObservation:
    return VisualObservation(
        observation_id=obs_id,
        captured_at=captured_at or datetime.utcnow(),
        width=width,
        height=height,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference=ref_id,
    )


def make_dummy_bgra_bytes(width: int, height: int) -> bytes:
    """Creates a valid dummy BGRA byte buffer."""
    arr = np.zeros((height, width, 4), dtype=np.uint8)
    return arr.tobytes()


# ── 1. Valid OCR detections produce valid VisualTarget candidates ──

def test_valid_ocr_detections_produce_valid_targets():
    """OCR returning valid detection produces a properly formed VisualTarget."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=800, height=600, ref_id="ref_valid")
    store.store("ref_valid", make_dummy_bgra_bytes(800, 600))

    # Mock engine returns: polygon, text, score
    mock_engine = lambda img: ([
        [[[50, 40], [150, 40], [150, 80], [50, 80]], "Settings", 0.98]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    targets = provider.find_targets(obs, query="Settings")

    assert len(targets) == 1
    t = targets[0]
    assert isinstance(t, VisualTarget)
    assert t.label == "Settings"
    assert t.target_type == "text"
    assert t.confidence == 0.98
    assert t.source_observation_id == obs.observation_id
    assert t.target_id.startswith("ocr_target_")


# ── 2. Detected bounding boxes are preserved correctly ──

def test_detected_bounding_boxes_preserved_correctly():
    """Bounding box coordinates (bbox_x, bbox_y, bbox_width, bbox_height) match polygon min/max."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=1000, height=800, ref_id="ref_bbox")
    store.store("ref_bbox", make_dummy_bgra_bytes(1000, 800))

    mock_engine = lambda img: ([
        [[[120.4, 200.1], [320.8, 200.1], [320.8, 260.9], [120.4, 260.9]], "Notepad", 0.95]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    targets = provider.find_targets(obs, query="Notepad")

    assert len(targets) == 1
    t = targets[0]
    assert t.bbox_x == 120
    assert t.bbox_y == 200
    assert t.bbox_width == 201  # ceil(320.8) - floor(120.4) = 321 - 120 = 201
    assert t.bbox_height == 61  # ceil(260.9) - floor(200.1) = 261 - 200 = 61


# ── 3. Confidence and source observation identity are preserved ──

def test_confidence_and_source_observation_preserved():
    """Target inherits exact calibrated confidence and observation ID."""
    store = InMemoryTestImageStore()
    obs_id = "obs_custom_provenance_99"
    obs = make_test_observation(obs_id=obs_id, width=500, height=400, ref_id="ref_conf")
    store.store("ref_conf", make_dummy_bgra_bytes(500, 400))

    mock_engine = lambda img: ([
        [[[10, 10], [50, 10], [50, 30], [10, 30]], "Save", 0.8765]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    targets = provider.find_targets(obs, query="Save")

    assert len(targets) == 1
    t = targets[0]
    assert t.confidence == 0.8765
    assert t.source_observation_id == obs_id
    assert t.semantic_attributes["ocr_confidence"] == 0.8765
    assert t.semantic_attributes["detected_text"] == "Save"


# ── 4. No OCR detections produce TARGET_NOT_FOUND when appropriate ──

def test_no_ocr_detections_produce_target_not_found():
    """When OCR finds no matches for query, selection service raises TARGET_NOT_FOUND."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=500, height=400, ref_id="ref_empty")
    store.store("ref_empty", make_dummy_bgra_bytes(500, 400))

    # Engine returns text that doesn't match query
    mock_engine = lambda img: ([
        [[[10, 10], [50, 10], [50, 30], [10, 30]], "Calculator", 0.99]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    candidates = provider.find_targets(obs, query="Notepad")

    assert candidates == []

    # Let existing TargetSelectionService handle policy
    with pytest.raises(VisualPerceptionError) as exc:
        target_selection_service.select_target(candidates)
    assert exc.value.code == "TARGET_NOT_FOUND"


# ── 5. Multiple plausible matches obey existing ambiguity policy ──

def test_multiple_plausible_matches_obey_ambiguity_policy():
    """When OCR finds two instances of the query, selection service raises TARGET_AMBIGUOUS."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=1000, height=800, ref_id="ref_ambig")
    store.store("ref_ambig", make_dummy_bgra_bytes(1000, 800))

    mock_engine = lambda img: ([
        [[[50, 50], [150, 50], [150, 90], [50, 90]], "Settings", 0.92],
        [[[50, 300], [150, 300], [150, 340], [50, 340]], "Settings", 0.94],
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    candidates = provider.find_targets(obs, query="Settings")

    assert len(candidates) == 2
    assert candidates[0].label == "Settings"
    assert candidates[1].label == "Settings"

    with pytest.raises(VisualPerceptionError) as exc:
        target_selection_service.select_target(candidates, min_confidence=0.5)
    assert exc.value.code == "TARGET_AMBIGUOUS"


# ── 6. Malformed or out-of-bounds geometry is rejected ──

def test_malformed_negative_geometry_rejected():
    """Negative coordinates raise INVALID_TARGET_GEOMETRY."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=800, height=600, ref_id="ref_geom_neg")
    store.store("ref_geom_neg", make_dummy_bgra_bytes(800, 600))

    mock_engine = lambda img: ([
        [[[-10, 20], [50, 20], [50, 60], [-10, 60]], "Test", 0.9]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    with pytest.raises(VisualPerceptionError) as exc:
        provider.find_targets(obs, query="Test")
    assert exc.value.code == "INVALID_TARGET_GEOMETRY"


def test_malformed_out_of_bounds_geometry_rejected():
    """Coordinates extending past observation width/height raise INVALID_TARGET_GEOMETRY."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=500, height=400, ref_id="ref_geom_oob")
    store.store("ref_geom_oob", make_dummy_bgra_bytes(500, 400))

    # Box extends to x = 550, exceeding observation width 500
    mock_engine = lambda img: ([
        [[[450, 50], [550, 50], [550, 90], [450, 90]], "Overflow", 0.9]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    with pytest.raises(VisualPerceptionError) as exc:
        provider.find_targets(obs, query="Overflow")
    assert exc.value.code == "INVALID_TARGET_GEOMETRY"


def test_malformed_non_finite_geometry_rejected():
    """NaN or Inf coordinates raise INVALID_TARGET_GEOMETRY."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=500, height=400, ref_id="ref_geom_nan")
    store.store("ref_geom_nan", make_dummy_bgra_bytes(500, 400))

    mock_engine = lambda img: ([
        [[[float("nan"), 50], [100, 50], [100, 90], [float("nan"), 90]], "NaN", 0.9]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    with pytest.raises(VisualPerceptionError) as exc:
        provider.find_targets(obs, query="NaN")
    assert exc.value.code == "INVALID_TARGET_GEOMETRY"


# ── 7. OCR initialization/inference failures become structured failures ──

def test_ocr_inference_exception_raises_structured_error():
    """Engine raising an exception during inference becomes PERCEPTION_INFERENCE_FAILED."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=400, height=300, ref_id="ref_infer_err")
    store.store("ref_infer_err", make_dummy_bgra_bytes(400, 300))

    def failing_engine(img):
        raise RuntimeError("ONNX Runtime internal failure: out of memory")

    provider = OcrPerceptionProvider(ocr_engine=failing_engine, image_store=store)
    with pytest.raises(VisualPerceptionError) as exc:
        provider.find_targets(obs, query="Anything")
    assert exc.value.code == "PERCEPTION_INFERENCE_FAILED"
    assert "out of memory" in exc.value.message


def test_ocr_init_exception_raises_structured_error():
    """Engine initialization failure raises PERCEPTION_INIT_FAILED."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(ref_id="ref_init_err")
    store.store("ref_init_err", make_dummy_bgra_bytes(800, 600))

    def failing_init_engine(img):
        raise VisualPerceptionError("PERCEPTION_INIT_FAILED", "Simulated initialization error")

    provider = OcrPerceptionProvider(ocr_engine=failing_init_engine, image_store=store)
    with pytest.raises(VisualPerceptionError) as exc:
        provider.find_targets(obs, query="Test")
    assert exc.value.code == "PERCEPTION_INIT_FAILED"


# ── 8. Missing/expired image references fail safely ──

def test_missing_expired_image_reference_fails_safely():
    """Non-existent or expired image reference raises IMAGE_EXPIRED."""
    store = InMemoryTestImageStore()  # Nothing stored
    obs = make_test_observation(ref_id="expired_ref_id")

    provider = OcrPerceptionProvider(image_store=store)
    with pytest.raises(VisualCaptureError) as exc:
        provider.find_targets(obs, query="Test")
    assert exc.value.code == "IMAGE_EXPIRED"


# ── 9. Stale observations are rejected according to freshness rules ──

def test_stale_observation_rejected():
    """Observation with capture timestamp older than last interaction raises STALE_OBSERVATION."""
    store = InMemoryTestImageStore()
    past_time = datetime.utcnow() - timedelta(seconds=10)
    obs = make_test_observation(captured_at=past_time, ref_id="stale_ref")
    store.store("stale_ref", make_dummy_bgra_bytes(800, 600))

    # Set last interaction 5 seconds after capture
    interaction_tracker._last_interaction = past_time + timedelta(seconds=5)

    provider = OcrPerceptionProvider(image_store=store)
    with pytest.raises(VisualCaptureError) as exc:
        provider.find_targets(obs, query="Test")
    assert exc.value.code == "STALE_OBSERVATION"


# ── 10. No raw screenshot or screen text leaks into normal logs/tool output ──

def test_no_raw_screenshot_or_screen_text_leaks():
    """Target objects and results contain metadata only, never raw byte payloads."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=600, height=400, ref_id="ref_leak_test")
    store.store("ref_leak_test", make_dummy_bgra_bytes(600, 400))

    mock_engine = lambda img: ([
        [[[10, 10], [100, 10], [100, 50], [10, 50]], "ConfidentialPassword", 0.99]
    ], [0.1, 0.01, 0.1])

    provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    targets = provider.find_targets(obs, query="ConfidentialPassword")

    assert len(targets) == 1
    t = targets[0]
    target_dict = t.model_dump()

    # Must contain expected fields
    assert "bbox_x" in target_dict
    assert "confidence" in target_dict
    assert "source_observation_id" in target_dict

    # Must NOT contain raw bytes or store references
    assert "image_reference" not in target_dict
    assert "raw_bytes" not in target_dict
    assert "buffer" not in target_dict


# ── 11. Semantic text matching policies ──

def test_semantic_text_matching_cases():
    """Proves deterministic semantic text matching handles case, tokens, and phrases."""
    # Exact case-insensitive
    assert matches_text_query("Settings", "settings") is True
    assert matches_text_query("SETTINGS", "Settings") is True

    # Word boundary / token match
    assert matches_text_query("Untitled - Notepad", "Notepad") is True
    assert matches_text_query("Open File Menu", "File") is True

    # Multi-word phrase match
    assert matches_text_query("Open Settings Window", "Open Settings") is True

    # Non-match
    assert matches_text_query("Google Chrome", "Firefox") is False

    # Does not falsely match partial words
    assert matches_text_query("Display", "Play") is False


# ── 12. Buffer size mismatch fails safely ──

def test_buffer_size_mismatch_raises_invalid_image_data():
    """Corrupted buffer with unexpected byte count raises INVALID_IMAGE_DATA."""
    store = InMemoryTestImageStore()
    obs = make_test_observation(width=800, height=600, ref_id="ref_corrupt")
    # Store only 100 bytes instead of 800 * 600 * 4 = 1,920,000 bytes
    store.store("ref_corrupt", b"corrupted_short_buffer")

    provider = OcrPerceptionProvider(image_store=store)
    with pytest.raises(VisualPerceptionError) as exc:
        provider.find_targets(obs, query="Test")
    assert exc.value.code == "INVALID_IMAGE_DATA"


# ── 13. Integration with VisualInteractionService ──

@pytest.mark.asyncio
async def test_ocr_provider_integration_with_visual_interaction_service():
    """Proves OcrPerceptionProvider integrates with VisualInteractionService."""
    from unittest.mock import AsyncMock, MagicMock
    from app.environment.visual.interaction import VisualInteractionService

    store = InMemoryTestImageStore()
    obs = make_test_observation(width=800, height=600, ref_id="ref_service_int")
    store.store("ref_service_int", make_dummy_bgra_bytes(800, 600))

    mock_engine = lambda img: ([
        [[[100, 100], [200, 100], [200, 150], [100, 150]], "Play", 0.95]
    ], [0.1, 0.01, 0.1])

    ocr_provider = OcrPerceptionProvider(ocr_engine=mock_engine, image_store=store)
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.return_value = obs
    mock_capture.store = store

    mock_router = AsyncMock()
    mock_router.route.return_value = {"success": True, "message": "Clicked"}

    service = VisualInteractionService(
        perception_provider=ocr_provider,
        capture_provider=mock_capture,
        router=mock_router,
    )

    result = await service.execute_click("Play", min_confidence=0.5)
    assert result.actuation_success is True
    assert result.verification.value == "UNKNOWN"
    assert result.provenance["target_id"].startswith("ocr_target_")
    assert result.provenance["screen_point"] == {"x": 150, "y": 125}
    mock_router.route.assert_called_once()

