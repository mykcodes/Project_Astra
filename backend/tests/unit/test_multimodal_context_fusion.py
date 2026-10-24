from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import pytest

from app.domain.visual import VisualObservation, VisualTarget
from app.domain.observation import AudioUtteranceContext, MultimodalObservation
from app.environment.models import WindowEntity
from app.interaction.models import UIElement, UIElementState, BoundingRectangle
from app.ai.context.fusion import MultimodalContextFusion


def test_fusion_with_matching_interactive_uia_element():
    fusion = MultimodalContextFusion()
    now = datetime.now(timezone.utc)

    vis_obs = VisualObservation(
        observation_id="vis_fuse_1",
        captured_at=now,
        width=1920,
        height=1080,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref1",
    )

    ocr_t = VisualTarget(
        target_id="ocr_1",
        label="Save Document",
        target_type="text",
        confidence=0.85,
        bbox_x=100,
        bbox_y=200,
        bbox_width=120,
        bbox_height=30,
        source_observation_id="vis_fuse_1",
    )

    uia_el = UIElement(
        runtime_id="uia_btn_save",
        name="Save Document",
        control_type="Button",
        automation_id="btnSave",
        class_name="Button",
        framework_id="WPF",
        process_id=1234,
        window_handle=5678,
        state=UIElementState(enabled=True, visible=True),
        bounding_rectangle=BoundingRectangle(left=95, top=195, right=225, bottom=235),
        supported_patterns=["Invoke"],
    )

    win = WindowEntity(
        hwnd=5678,
        title="Editor",
        pid=1234,
        process_name="editor.exe",
        visible=True,
        minimized=False,
        foreground=True,
        fullscreen=False,
        monitor=0,
        x=0,
        y=0,
        width=1920,
        height=1080,
    )

    mm_obs = fusion.fuse_observation(
        visual_obs=vis_obs,
        ocr_targets=[ocr_t],
        active_window=win,
        ui_elements=[uia_el],
    )

    assert len(mm_obs.text_detections) == 1
    fused = mm_obs.text_detections[0]
    assert fused.target_type == "interactive"
    assert fused.confidence > ocr_t.confidence  # Boosted from dual evidence
    assert fused.semantic_attributes["uia_matched"] is True
    assert fused.semantic_attributes["control_type"] == "Button"
    assert fused.semantic_attributes["automation_id"] == "btnSave"
    assert fused.semantic_attributes["is_interactive_control"] is True
    assert fused.semantic_attributes["provenance_modalities"] == ["OCR", "UIA"]
    assert mm_obs.modality_availability["uia"] is True


def test_fusion_with_disabled_control():
    fusion = MultimodalContextFusion()
    now = datetime.now(timezone.utc)

    vis_obs = VisualObservation(
        observation_id="vis_fuse_2",
        captured_at=now,
        width=1000,
        height=800,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref2",
    )

    ocr_t = VisualTarget(
        target_id="ocr_2",
        label="Redo",
        target_type="text",
        confidence=0.9,
        bbox_x=50,
        bbox_y=50,
        bbox_width=60,
        bbox_height=20,
        source_observation_id="vis_fuse_2",
    )

    uia_disabled = UIElement(
        runtime_id="uia_btn_redo",
        name="Redo",
        control_type="Button",
        automation_id="btnRedo",
        class_name="Button",
        framework_id="WPF",
        process_id=1234,
        window_handle=5678,
        state=UIElementState(enabled=False, visible=True),  # DISABLED
        bounding_rectangle=BoundingRectangle(left=45, top=45, right=115, bottom=75),
    )

    mm_obs = fusion.fuse_observation(
        visual_obs=vis_obs,
        ocr_targets=[ocr_t],
        ui_elements=[uia_disabled],
    )

    fused = mm_obs.text_detections[0]
    assert fused.semantic_attributes["disabled"] is True
    assert fused.semantic_attributes["enabled"] is False


def test_fusion_graceful_without_uia():
    fusion = MultimodalContextFusion()
    now = datetime.now(timezone.utc)

    vis_obs = VisualObservation(
        observation_id="vis_fuse_3",
        captured_at=now,
        width=800,
        height=600,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref3",
    )

    ocr_t = VisualTarget(
        target_id="ocr_3",
        label="Plain Text",
        target_type="text",
        confidence=0.92,
        bbox_x=10,
        bbox_y=10,
        bbox_width=100,
        bbox_height=20,
        source_observation_id="vis_fuse_3",
    )

    mm_obs = fusion.fuse_observation(
        visual_obs=vis_obs,
        ocr_targets=[ocr_t],
        ui_elements=None,
    )

    fused = mm_obs.text_detections[0]
    assert fused.semantic_attributes["uia_matched"] is False
    assert fused.semantic_attributes["is_interactive_control"] is False
    assert fused.semantic_attributes["provenance_modalities"] == ["OCR"]
    assert mm_obs.modality_availability["uia"] is False


def test_speech_observation_temporal_alignment():
    fusion = MultimodalContextFusion()
    t0 = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)

    # 3 snapshots at t0, t0 + 1s, t0 + 2s
    obs1 = MagicMock(spec=MultimodalObservation)
    obs1.observation_id = "obs_t0"
    obs1.captured_at_utc = t0

    obs2 = MagicMock(spec=MultimodalObservation)
    obs2.observation_id = "obs_t1"
    obs2.captured_at_utc = t0 + timedelta(seconds=1.0)

    obs3 = MagicMock(spec=MultimodalObservation)
    obs3.observation_id = "obs_t2"
    obs3.captured_at_utc = t0 + timedelta(seconds=2.0)

    history = [obs1, obs2, obs3]

    # Utterance occurred at t0 + 1.1s (should pair with obs2)
    utt = AudioUtteranceContext(
        utterance_id="utt_test",
        start_time_utc=t0 + timedelta(seconds=1.1),
        transcript_text="Click Save",
    )

    aligned = fusion.align_utterance_to_observation(utt, history, max_tolerance_s=0.5)
    assert aligned is not None
    assert aligned.observation_id == "obs_t1"
    assert utt.aligned_observation_id == "obs_t1"

    # Utterance far away at t0 + 10s (should be rejected)
    utt_far = AudioUtteranceContext(
        utterance_id="utt_far",
        start_time_utc=t0 + timedelta(seconds=10.0),
        transcript_text="Click Help",
    )
    aligned_far = fusion.align_utterance_to_observation(utt_far, history, max_tolerance_s=2.0)
    assert aligned_far is None
    assert utt_far.aligned_observation_id is None
