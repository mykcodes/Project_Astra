import json
import pytest
from datetime import datetime, timezone

from app.domain.entities import ScreenPoint
from app.domain.visual import VisualObservation, VisualTarget, VisualPerceptionError
from app.domain.observation import (
    CoordinateSpace,
    CoordinateTransformError,
    BoundingBox,
    image_to_virtual_screen,
    virtual_screen_to_image,
    virtual_screen_to_window,
    window_to_virtual_screen,
    transform_bbox,
    AudioUtteranceContext,
    PerceptualDiffResult,
    TrackedTarget,
    MultimodalObservation,
)
from app.environment.visual.selection import TargetSelectionService
from app.environment.models import WindowEntity


def test_bounding_box_properties_and_tuple():
    box = BoundingBox(x=100.0, y=200.0, width=50.0, height=80.0, coordinate_space=CoordinateSpace.IMAGE_LOCAL)
    assert box.right == 150.0
    assert box.bottom == 280.0
    assert box.center == (125.0, 240.0)
    assert box.as_tuple() == (100, 200, 50, 80)


def test_coordinate_transforms_image_and_virtual_screen():
    # Test positive virtual offset (primary display at origin)
    pt = image_to_virtual_screen(
        image_x=100,
        image_y=150,
        virtual_offset_x=0,
        virtual_offset_y=0,
        capture_width=1920,
        capture_height=1080,
    )
    assert pt.x == 100
    assert pt.y == 150

    img_x, img_y = virtual_screen_to_image(
        screen_x=100,
        screen_y=150,
        virtual_offset_x=0,
        virtual_offset_y=0,
        capture_width=1920,
        capture_height=1080,
    )
    assert img_x == 100
    assert img_y == 150


def test_coordinate_transforms_negative_virtual_screen_origin():
    # Multi-monitor setup where monitor 2 is to the left at x=-1920, y=0
    # Capture spans from -1920 to 1920 (width=3840)
    pt = image_to_virtual_screen(
        image_x=200,
        image_y=300,
        virtual_offset_x=-1920,
        virtual_offset_y=0,
        capture_width=3840,
        capture_height=1080,
    )
    assert pt.x == -1720
    assert pt.y == 300

    img_x, img_y = virtual_screen_to_image(
        screen_x=-1720,
        screen_y=300,
        virtual_offset_x=-1920,
        virtual_offset_y=0,
        capture_width=3840,
        capture_height=1080,
    )
    assert img_x == 200
    assert img_y == 300


def test_coordinate_transforms_out_of_bounds_raises_without_silent_clamping():
    with pytest.raises(CoordinateTransformError) as exc_info:
        image_to_virtual_screen(
            image_x=2000,
            image_y=500,
            virtual_offset_x=0,
            virtual_offset_y=0,
            capture_width=1920,
            capture_height=1080,
            validate=True,
        )
    assert exc_info.value.code == "OUT_OF_IMAGE_BOUNDS"

    with pytest.raises(CoordinateTransformError) as exc_info:
        virtual_screen_to_image(
            screen_x=5000,
            screen_y=500,
            virtual_offset_x=0,
            virtual_offset_y=0,
            capture_width=1920,
            capture_height=1080,
            validate=True,
        )
    assert exc_info.value.code == "OUT_OF_IMAGE_BOUNDS"


def test_window_relative_coordinate_transforms():
    win_bounds = (100, 200, 800, 600)  # (x, y, w, h)
    rel_x, rel_y = virtual_screen_to_window(screen_x=250, screen_y=350, window_bounds=win_bounds)
    assert rel_x == 150
    assert rel_y == 150

    screen_pt = window_to_virtual_screen(rel_x=150, rel_y=150, window_bounds=win_bounds)
    assert screen_pt.x == 250
    assert screen_pt.y == 350

    with pytest.raises(CoordinateTransformError) as exc_info:
        virtual_screen_to_window(screen_x=50, screen_y=50, window_bounds=win_bounds, validate=True)
    assert exc_info.value.code == "OUT_OF_WINDOW_BOUNDS"


def test_transform_bbox_across_spaces():
    # IMAGE_LOCAL to VIRTUAL_SCREEN with offset
    box_img = BoundingBox(x=50, y=60, width=100, height=40, coordinate_space=CoordinateSpace.IMAGE_LOCAL)
    box_virt = transform_bbox(
        box_img,
        target_space=CoordinateSpace.VIRTUAL_SCREEN,
        virtual_offset_x=-1920,
        virtual_offset_y=100,
    )
    assert box_virt.coordinate_space == CoordinateSpace.VIRTUAL_SCREEN
    assert box_virt.x == -1870
    assert box_virt.y == 160
    assert box_virt.width == 100
    assert box_virt.height == 40

    # VIRTUAL_SCREEN to WINDOW_RELATIVE
    win_bounds = (-1900, 100, 600, 400)
    box_win = transform_bbox(
        box_virt,
        target_space=CoordinateSpace.WINDOW_RELATIVE,
        window_bounds=win_bounds,
    )
    assert box_win.coordinate_space == CoordinateSpace.WINDOW_RELATIVE
    assert box_win.x == 30
    assert box_win.y == 60


def test_target_selection_multi_monitor_virtual_offset_disambiguation():
    service = TargetSelectionService()

    # Candidate in image local space: candidate 1 is on monitor 2 (x=2000, y=100), candidate 2 is on monitor 1 (x=100, y=100)
    t1 = VisualTarget(
        target_id="cand_1",
        label="Save",
        target_type="text",
        confidence=0.9,
        bbox_x=100,
        bbox_y=100,
        bbox_width=60,
        bbox_height=25,
        source_observation_id="obs_1",
    )
    t2 = VisualTarget(
        target_id="cand_2",
        label="Save",
        target_type="text",
        confidence=0.9,
        bbox_x=2020,
        bbox_y=100,
        bbox_width=60,
        bbox_height=25,
        source_observation_id="obs_1",
    )

    # Window bounds on monitor 2 in virtual space: x=2000, y=50, w=800, h=600
    # Capture has virtual_offset = (0, 0)
    selected = service.select_target(
        candidates=[t1, t2],
        target_bounds=(2000, 50, 800, 600),
        virtual_offset=(0, 0),
        query="Save",
    )
    assert selected.target_id == "cand_2"

    # Now consider monitor 1 with negative virtual offset (-1920, 0)
    # Target bounds on virtual screen: (-1850, 80, 500, 400)
    # Candidate in image space: bbox_x=70, so bbox_x + (-1920) = -1850
    t_neg = VisualTarget(
        target_id="cand_neg",
        label="File",
        target_type="text",
        confidence=0.95,
        bbox_x=70,
        bbox_y=90,
        bbox_width=40,
        bbox_height=20,
        source_observation_id="obs_2",
    )
    t_other = VisualTarget(
        target_id="cand_other",
        label="File",
        target_type="text",
        confidence=0.95,
        bbox_x=2000,
        bbox_y=90,
        bbox_width=40,
        bbox_height=20,
        source_observation_id="obs_2",
    )
    selected_neg = service.select_target(
        candidates=[t_neg, t_other],
        target_bounds=(-1850, 80, 500, 400),
        virtual_offset=(-1920, 0),
        query="File",
    )
    assert selected_neg.target_id == "cand_neg"


def test_multimodal_observation_serialization_round_trip():
    now = datetime.now(timezone.utc)
    vis_obs = VisualObservation(
        observation_id="vis_123",
        captured_at=now,
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="img_ref_abc",
    )

    t1 = VisualTarget(
        target_id="t_1",
        label="OK",
        target_type="text",
        confidence=0.98,
        bbox_x=100,
        bbox_y=200,
        bbox_width=50,
        bbox_height=25,
        source_observation_id="vis_123",
    )

    audio_ctx = AudioUtteranceContext(
        utterance_id="utt_1",
        client_timestamp_ms=1690000000.0,
        start_time_utc=now,
        end_time_utc=now,
        transcript_text="Click OK",
        clock_domain="CLIENT_MONOTONIC",
        aligned_observation_id="mm_1",
    )

    diff_res = PerceptualDiffResult(
        has_changed=True,
        change_ratio=0.012,
        damage_region=(100, 200, 50, 50),
        diff_hash="hash123",
        ocr_suppressed=False,
        forced_refresh=False,
        duration_ms=2.5,
    )

    mm_obs = MultimodalObservation(
        observation_id="mm_1",
        captured_at_utc=now,
        visual=vis_obs,
        is_full_virtual_desktop=True,
        capture_region=(0, 0, 1920, 1080),
        text_detections=[t1],
        active_window=WindowEntity(
            hwnd=12345,
            title="App",
            pid=999,
            process_name="app.exe",
            visible=True,
            minimized=False,
            foreground=True,
            fullscreen=False,
            monitor=0,
            x=0,
            y=0,
            width=1000,
            height=800,
        ),
        audio_context=audio_ctx,
        spatial_hash="spatial_hash_xyz",
        diff_from_previous=diff_res,
        modality_availability={"visual": True, "ocr": True, "uia": False, "audio": True},
    )

    # Test JSON serialization and deserialization
    json_str = mm_obs.model_dump_json()
    data = json.loads(json_str)
    assert data["observation_id"] == "mm_1"
    assert data["visual"]["width"] == 1920
    assert len(data["text_detections"]) == 1
    assert data["text_detections"][0]["label"] == "OK"
    assert data["audio_context"]["transcript_text"] == "Click OK"
    assert data["diff_from_previous"]["change_ratio"] == 0.012

    restored = MultimodalObservation.model_validate_json(json_str)
    assert restored.observation_id == mm_obs.observation_id
    assert restored.capture_region == (0, 0, 1920, 1080)
    assert restored.text_detections[0].bbox_x == 100
