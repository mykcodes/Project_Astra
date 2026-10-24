import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from app.core.logging.logger import get_logger
from app.domain.entities import ScreenPoint
from app.domain.visual import VisualObservation, VisualTarget
from app.domain.observation import (
    AudioUtteranceContext,
    BoundingBox,
    CoordinateSpace,
    MultimodalObservation,
    PerceptualDiffResult,
    MULTIMODAL_SCHEMA_VERSION,
)
from app.environment.models import WindowEntity
from app.interaction.models import UIElement, BoundingRectangle

logger = get_logger(__name__)


def _rect_intersects_box(
    rect: BoundingRectangle,
    screen_x: float,
    screen_y: float,
    width: float,
    height: float,
) -> bool:
    """Checks if a UIA BoundingRectangle intersects screen-space box."""
    if not rect:
        return False
    inter_x1 = max(rect.left, screen_x)
    inter_y1 = max(rect.top, screen_y)
    inter_x2 = min(rect.right, screen_x + width)
    inter_y2 = min(rect.bottom, screen_y + height)
    return inter_x2 > inter_x1 and inter_y2 > inter_y1


class MultimodalContextFusion:
    """
    Deterministic context fusion layer uniting OCR text detections,
    UIAutomation element evidence, window geometry, and speech context.
    
    Responsibilities:
    - Cross-modal target alignment between OCR bounding boxes and UIA controls.
    - Deterministic contradiction resolution (disabled controls, label divergence).
    - Modality provenance tracking (preserves whether evidence came from OCR, UIA, or both).
    - Temporal alignment between voice utterances and desktop observation snapshots.
    - Zero cloud vision API dependencies; 100% deterministic local rules.
    """

    def fuse_observation(
        self,
        visual_obs: VisualObservation,
        ocr_targets: List[VisualTarget],
        active_window: Optional[WindowEntity] = None,
        ui_elements: Optional[List[UIElement]] = None,
        audio_context: Optional[AudioUtteranceContext] = None,
        diff_result: Optional[PerceptualDiffResult] = None,
    ) -> MultimodalObservation:
        """
        Fuses disparate perception modalities into a unified MultimodalObservation.
        """
        fused_targets: List[VisualTarget] = []
        vox = visual_obs.virtual_offset_x
        voy = visual_obs.virtual_offset_y

        uia_map: Dict[str, UIElement] = {}
        if ui_elements:
            for el in ui_elements:
                uia_map[el.runtime_id] = el

        for target in ocr_targets:
            # Map candidate bbox to virtual screen coordinates for UIA cross-matching
            cand_sx = target.bbox_x + vox
            cand_sy = target.bbox_y + voy
            cand_w = target.bbox_width
            cand_h = target.bbox_height

            matched_uia: Optional[UIElement] = None
            if ui_elements:
                # Find matching UIA element by bounding rectangle intersection and label
                t_label = target.label.strip().strip("'\"`&_ ").lower()
                for el in ui_elements:
                    if el.bounding_rectangle and _rect_intersects_box(
                        el.bounding_rectangle, cand_sx, cand_sy, cand_w, cand_h
                    ):
                        matched_uia = el
                        el_name = (el.name or "").strip().strip("'\"`&_ ").lower()
                        if t_label in el_name or el_name in t_label:
                            break  # Exact name + intersection match

            # Build enriched semantic attributes
            attrs = dict(target.semantic_attributes)
            if active_window:
                attrs["window_hwnd"] = active_window.hwnd
                attrs["window_title"] = active_window.title

            if matched_uia:
                is_interactive = (
                    matched_uia.control_type in (
                        "Button", "MenuItem", "CheckBox", "RadioButton",
                        "TabItem", "Hyperlink", "SplitButton", "Edit", "ComboBox"
                    )
                    or bool(matched_uia.supported_patterns)
                )
                attrs["uia_matched"] = True
                attrs["uia_runtime_id"] = matched_uia.runtime_id
                attrs["automation_id"] = matched_uia.automation_id
                attrs["control_type"] = matched_uia.control_type
                attrs["is_interactive_control"] = is_interactive
                attrs["enabled"] = matched_uia.state.enabled
                attrs["supported_patterns"] = matched_uia.supported_patterns
                attrs["provenance_modalities"] = ["OCR", "UIA"]

                if not matched_uia.state.enabled:
                    attrs["disabled"] = True

                # Confidence boost from dual modality confirmation
                boosted_conf = min(1.0, target.confidence * 0.4 + 0.6)
            else:
                attrs["uia_matched"] = False
                attrs["is_interactive_control"] = False
                attrs["provenance_modalities"] = ["OCR"]
                boosted_conf = target.confidence

            fused_targets.append(
                VisualTarget(
                    target_id=target.target_id,
                    label=target.label,
                    target_type="interactive" if attrs.get("is_interactive_control") else target.target_type,
                    confidence=round(boosted_conf, 3),
                    bbox_x=target.bbox_x,
                    bbox_y=target.bbox_y,
                    bbox_width=target.bbox_width,
                    bbox_height=target.bbox_height,
                    source_observation_id=target.source_observation_id,
                    semantic_attributes=attrs,
                )
            )

        # Spatial digest hashing
        h = hashlib.sha256()
        h.update(f"{visual_obs.width}x{visual_obs.height}".encode())
        if active_window:
            h.update(f"{active_window.hwnd}|{active_window.title}".encode())
        for t in sorted(fused_targets, key=lambda x: (x.bbox_y, x.bbox_x)):
            h.update(f"{t.label}|{t.bbox_x},{t.bbox_y}".encode())
        spatial_hash = h.hexdigest()[:16]

        capture_region = (vox, voy, visual_obs.width, visual_obs.height)
        modality_avail = {
            "visual": True,
            "ocr": len(fused_targets) > 0 or (diff_result and diff_result.ocr_suppressed),
            "window": active_window is not None,
            "uia": ui_elements is not None and len(ui_elements) > 0,
            "audio": audio_context is not None,
        }

        return MultimodalObservation(
            observation_id=f"mm_{visual_obs.observation_id}",
            schema_version=MULTIMODAL_SCHEMA_VERSION,
            captured_at_utc=visual_obs.captured_at,
            visual=visual_obs,
            is_full_virtual_desktop=True,
            capture_region=capture_region,
            text_detections=fused_targets,
            active_window=active_window,
            ui_elements=ui_elements,
            audio_context=audio_context,
            spatial_hash=spatial_hash,
            diff_from_previous=diff_result,
            modality_availability=modality_avail,
        )

    def align_utterance_to_observation(
        self,
        utterance_context: AudioUtteranceContext,
        observation_history: List[MultimodalObservation],
        max_tolerance_s: float = 3.0,
    ) -> Optional[MultimodalObservation]:
        """
        Aligns a speech utterance with desktop observation from the exact time of speech.
        
        Rules:
        - Matches utterance.start_time_utc against observation.captured_at_utc.
        - Accounts for clock domain differences and enforces max_tolerance_s.
        - Rejects unverified or out-of-bounds pairings.
        """
        if not observation_history:
            return None

        best_obs: Optional[MultimodalObservation] = None
        best_delta = float("inf")

        tgt = utterance_context.start_time_utc
        if tgt.tzinfo is None:
            tgt = tgt.replace(tzinfo=timezone.utc)

        for obs in observation_history:
            obs_t = obs.captured_at_utc
            if obs_t.tzinfo is None:
                obs_t = obs_t.replace(tzinfo=timezone.utc)

            delta = abs((obs_t - tgt).total_seconds())
            if delta <= max_tolerance_s and delta < best_delta:
                best_delta = delta
                best_obs = obs

        if best_obs:
            utterance_context.aligned_observation_id = best_obs.observation_id
            logger.info(
                f"Aligned utterance '{utterance_context.utterance_id}' to observation "
                f"'{best_obs.observation_id}' (delta: {best_delta:.3f}s)."
            )
            return best_obs

        logger.warning(
            f"No matching observation within {max_tolerance_s}s tolerance for "
            f"utterance '{utterance_context.utterance_id}' at {tgt.isoformat()}."
        )
        return None


context_fusion = MultimodalContextFusion()
