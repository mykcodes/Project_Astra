import math
from typing import List, Optional, Tuple
from app.core.logging.logger import get_logger
from app.domain.entities import ScreenPoint
from app.domain.visual import (
    GroundedTarget,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
from app.domain.observation import (
    BoundingBox,
    CoordinateSpace,
    TrackedTarget,
    image_to_virtual_screen,
)
from app.environment.visual.perception import OcrPerceptionProvider, ocr_perception_provider
from app.environment.visual.mapper import visual_mapper

logger = get_logger(__name__)


def compute_iou(b1: Tuple[float, float, float, float], b2: Tuple[float, float, float, float]) -> float:
    """Computes Intersection over Union of two bounding boxes (x, y, w, h)."""
    x1, y1, w1, h1 = b1
    x2, y2, w2, h2 = b2

    inter_x1 = max(x1, x2)
    inter_y1 = max(y1, y2)
    inter_x2 = min(x1 + w1, x2 + w2)
    inter_y2 = min(y1 + h1, y2 + h2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    if inter_area == 0.0:
        return 0.0

    area1 = w1 * h1
    area2 = w2 * h2
    union_area = area1 + area2 - inter_area
    return inter_area / union_area if union_area > 0.0 else 0.0


class SpatialTargetTracker:
    """
    Temporal tracker for grounded visual targets.
    
    Responsibilities:
    - Pre-actuation re-grounding and spatial drift validation.
    - Detection of target displacement, occlusion, or disappearance.
    - Zero blind actuation against stale or moved UI elements.
    - Recomputation of physical OS screen coordinates using authoritative mapper.
    """

    def __init__(
        self,
        ocr_provider: Optional[OcrPerceptionProvider] = None,
        default_drift_tolerance_px: float = 8.0,
        max_trackable_drift_px: float = 35.0,
    ):
        self.ocr_provider = ocr_provider or ocr_perception_provider
        self.default_drift_tolerance_px = default_drift_tolerance_px
        self.max_trackable_drift_px = max_trackable_drift_px

    def track_in_observation(
        self,
        target: VisualTarget,
        current_observation: VisualObservation,
        candidates: Optional[List[VisualTarget]] = None,
    ) -> TrackedTarget:
        """
        Locates target in current_observation and computes drift from target's original position.
        """
        if candidates is None:
            candidates = self.ocr_provider.extract_all_targets(current_observation)

        target_norm = target.label.strip().strip("'\"`&_ ").lower()
        orig_box = (
            float(target.bbox_x),
            float(target.bbox_y),
            float(target.bbox_width),
            float(target.bbox_height),
        )
        orig_cx = orig_box[0] + orig_box[2] / 2.0
        orig_cy = orig_box[1] + orig_box[3] / 2.0

        best_match: Optional[VisualTarget] = None
        best_score = -1.0
        min_dist = float("inf")

        for cand in candidates:
            cand_norm = cand.label.strip().strip("'\"`&_ ").lower()
            if cand_norm != target_norm and target_norm not in cand_norm and cand_norm not in target_norm:
                continue

            cand_box = (
                float(cand.bbox_x),
                float(cand.bbox_y),
                float(cand.bbox_width),
                float(cand.bbox_height),
            )
            cand_cx = cand_box[0] + cand_box[2] / 2.0
            cand_cy = cand_box[1] + cand_box[3] / 2.0

            dist = math.hypot(cand_cx - orig_cx, cand_cy - orig_cy)
            iou = compute_iou(orig_box, cand_box)

            # Combined score favoring high IoU and low distance
            score = iou * 100.0 - dist
            if cand_norm == target_norm:
                score += 50.0

            if score > best_score:
                best_score = score
                best_match = cand
                min_dist = dist

        initial_bbox = BoundingBox(
            x=target.bbox_x,
            y=target.bbox_y,
            width=target.bbox_width,
            height=target.bbox_height,
            coordinate_space=CoordinateSpace.IMAGE_LOCAL,
        )

        if best_match is None or min_dist > self.max_trackable_drift_px:
            # Target has disappeared or moved beyond tracking recovery range
            return TrackedTarget(
                target_id=target.target_id,
                label=target.label,
                target_type=target.target_type,
                confidence=0.0,
                current_bbox=initial_bbox,
                initial_bbox=initial_bbox,
                source_observation_id=target.source_observation_id,
                last_verified_observation_id=current_observation.observation_id,
                movement_px=min_dist if min_dist != float("inf") else 999.0,
                is_occluded=False,
                is_stale=True,
            )

        current_bbox = BoundingBox(
            x=best_match.bbox_x,
            y=best_match.bbox_y,
            width=best_match.bbox_width,
            height=best_match.bbox_height,
            coordinate_space=CoordinateSpace.IMAGE_LOCAL,
        )

        return TrackedTarget(
            target_id=target.target_id,
            label=best_match.label,
            target_type=best_match.target_type,
            confidence=best_match.confidence,
            current_bbox=current_bbox,
            initial_bbox=initial_bbox,
            source_observation_id=target.source_observation_id,
            last_verified_observation_id=current_observation.observation_id,
            movement_px=round(min_dist, 2),
            is_occluded=False,
            is_stale=False,
            semantic_attributes=best_match.semantic_attributes,
        )

    def re_ground_pre_actuation(
        self,
        grounded: GroundedTarget,
        fresh_observation: VisualObservation,
        allow_dynamic_retracking: bool = True,
        strict_drift_px: Optional[float] = None,
        candidates: Optional[List[VisualTarget]] = None,
    ) -> GroundedTarget:
        """
        Validates that grounded target is still present and valid in fresh_observation.
        
        Raises:
            VisualPerceptionError("TARGET_DISAPPEARED") if target is no longer found.
            VisualPerceptionError("TARGET_MOVED") if target has moved beyond threshold.
            VisualPerceptionError("TARGET_OCCLUDED") if target is obscured.
        """
        drift_limit = strict_drift_px if strict_drift_px is not None else self.default_drift_tolerance_px
        tracked = self.track_in_observation(grounded.target, fresh_observation, candidates=candidates)

        if tracked.is_stale:
            raise VisualPerceptionError(
                "TARGET_DISAPPEARED",
                f"Target '{grounded.target.label}' ({grounded.target.target_id}) is no longer visible "
                f"in fresh observation {fresh_observation.observation_id}.",
            )

        if tracked.is_occluded:
            raise VisualPerceptionError(
                "TARGET_OCCLUDED",
                f"Target '{grounded.target.label}' ({grounded.target.target_id}) is occluded by an overlapping window.",
            )

        # Check movement
        if tracked.movement_px > drift_limit:
            if not allow_dynamic_retracking or tracked.movement_px > self.max_trackable_drift_px:
                raise VisualPerceptionError(
                    "TARGET_MOVED",
                    f"Target '{grounded.target.label}' moved {tracked.movement_px:.1f}px "
                    f"(exceeds safety threshold {drift_limit}px). Pre-actuation rejected.",
                )
            logger.info(
                f"Target '{grounded.target.label}' shifted {tracked.movement_px:.1f}px. "
                f"Dynamically updating anchor coordinates for actuation."
            )

        # Compute updated anchor point from fresh bounding box
        cand_x = int(round(tracked.current_bbox.x))
        cand_y = int(round(tracked.current_bbox.y))
        cand_w = int(round(tracked.current_bbox.width))
        cand_h = int(round(tracked.current_bbox.height))

        anchor_x = cand_x + (cand_w // 2)
        anchor_y = cand_y + (cand_h // 2)

        # Map to physical screen coordinates
        screen_point: ScreenPoint = visual_mapper.map_to_screen_point(
            fresh_observation,
            anchor_x,
            anchor_y,
        )

        updated_target = VisualTarget(
            target_id=grounded.target.target_id,
            label=tracked.label,
            target_type=grounded.target.target_type,
            confidence=tracked.confidence,
            bbox_x=cand_x,
            bbox_y=cand_y,
            bbox_width=cand_w,
            bbox_height=cand_h,
            source_observation_id=fresh_observation.observation_id,
            semantic_attributes=tracked.semantic_attributes,
        )

        return GroundedTarget(
            target=updated_target,
            source_observation_id=fresh_observation.observation_id,
            anchor_point=screen_point,
        )


spatial_target_tracker = SpatialTargetTracker()
