from typing import List, Optional, Tuple
from app.domain.visual import VisualTarget, VisualPerceptionError
from app.core.logging.logger import get_logger

logger = get_logger(__name__)


def _is_duplicate_detection(c1: VisualTarget, c2: VisualTarget) -> bool:
    """
    Checks if two OCR candidates represent the same underlying visual UI element
    (e.g., duplicate bounding box from multi-scale or word/line OCR passes).
    """
    norm1 = c1.label.strip().strip("'\"`&_ ").lower()
    norm2 = c2.label.strip().strip("'\"`&_ ").lower()
    if norm1 != norm2:
        return False

    center1_x = c1.bbox_x + (c1.bbox_width / 2.0)
    center1_y = c1.bbox_y + (c1.bbox_height / 2.0)
    center2_x = c2.bbox_x + (c2.bbox_width / 2.0)
    center2_y = c2.bbox_y + (c2.bbox_height / 2.0)

    # If centers are within 10 pixels on both axes
    if abs(center1_x - center2_x) <= 10 and abs(center1_y - center2_y) <= 10:
        return True

    # Calculate Intersection over Union (IoU)
    x1 = max(c1.bbox_x, c2.bbox_x)
    y1 = max(c1.bbox_y, c2.bbox_y)
    x2 = min(c1.bbox_x + c1.bbox_width, c2.bbox_x + c2.bbox_width)
    y2 = min(c1.bbox_y + c1.bbox_height, c2.bbox_y + c2.bbox_height)
    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter_area = inter_w * inter_h
    if inter_area == 0:
        return False

    area1 = c1.bbox_width * c1.bbox_height
    area2 = c2.bbox_width * c2.bbox_height
    union_area = area1 + area2 - inter_area
    iou = inter_area / union_area if union_area > 0 else 0.0
    return iou >= 0.5


class TargetSelectionService:
    """
    Selects a single visual target from a pool of candidates based on semantic and confidence policies.
    Responsibility: "Which candidate, if any, satisfies the semantic request?"
    """

    def select_target(
        self,
        candidates: List[VisualTarget],
        min_confidence: float = 0.5,
        target_bounds: Optional[Tuple[int, int, int, int]] = None,
        query: Optional[str] = None,
        virtual_offset: Tuple[int, int] = (0, 0),
    ) -> VisualTarget:
        """
        Evaluates candidates and selects exactly one target.
        Fails structured if ambiguous, not found, or confidence is too low.
        
        Args:
            candidates: OCR or visual target candidates in image-local coordinates.
            min_confidence: Minimum detection confidence threshold.
            target_bounds: Optional (win_x, win_y, win_w, win_h) in virtual screen coordinates.
            query: Semantic query text.
            virtual_offset: (virtual_offset_x, virtual_offset_y) screen offset of the image capture.
        """
        if not candidates:
            raise VisualPerceptionError("TARGET_NOT_FOUND", "Perception returned no candidates.")

        # Filter by confidence
        valid_candidates = [c for c in candidates if c.confidence >= min_confidence]

        if not valid_candidates:
            highest_conf = max(candidates, key=lambda x: x.confidence)
            raise VisualPerceptionError(
                "TARGET_CONFIDENCE_TOO_LOW",
                f"Candidates found, but highest confidence ({highest_conf.confidence}) is below threshold ({min_confidence}).",
            )

        # -----------------------------------------------------------------
        # Step 1: Exact match disambiguation
        # -----------------------------------------------------------------
        # If OCR returned both an exact word match (e.g. "File") and a multi-word line
        # containing that word (e.g. "File size" or "File Edit View"), prefer the exact match.
        if len(valid_candidates) > 1:
            eff_query = query
            if not eff_query:
                for c in valid_candidates:
                    if c.semantic_attributes and c.semantic_attributes.get("query"):
                        eff_query = str(c.semantic_attributes["query"])
                        break

            if eff_query:
                q_norm = eff_query.strip().strip("'\"`&_ ").lower()
                exact_matches = [
                    c for c in valid_candidates
                    if c.label.strip().strip("'\"`&_ ").lower() == q_norm
                ]
                if len(exact_matches) >= 1:
                    valid_candidates = exact_matches

        # -----------------------------------------------------------------
        # Step 2: Target window bounding box disambiguation
        # -----------------------------------------------------------------
        # When user interaction targets a specific window and multiple candidates exist,
        # prioritize candidates located inside the target window bounds.
        # Candidate coordinates are in image-local coordinates; target_bounds are in virtual-screen coordinates.
        # Apply virtual_offset (vox, voy) to convert candidate image coords to virtual-screen coords.
        if len(valid_candidates) > 1 and target_bounds:
            win_bounds = target_bounds
            if win_bounds:
                win_x, win_y, win_w, win_h = win_bounds
                vox, voy = virtual_offset
                in_win = [
                    c for c in valid_candidates
                    if (win_x - 10 <= c.bbox_x + vox <= win_x + win_w + 10)
                    and (win_y - 10 <= c.bbox_y + voy <= win_y + win_h + 10)
                ]
                if len(in_win) == 1:
                    valid_candidates = in_win
                elif len(in_win) > 1:
                    # If multiple candidates inside window, prioritize menu/header strip
                    max_menu_y = win_y + min(160, max(80, win_h // 3))
                    max_menu_x = win_x + min(500, max(250, win_w // 2))
                    in_menu = [
                        c for c in in_win
                        if (c.bbox_y + voy) <= max_menu_y and (c.bbox_x + vox) <= max_menu_x
                    ]
                    if len(in_menu) == 1:
                        valid_candidates = in_menu
                    elif len(in_menu) > 1:
                        # Topmost candidate in the menu strip
                        topmost = min(in_menu, key=lambda c: (c.bbox_y + voy, c.bbox_x + vox))
                        valid_candidates = [topmost]

        # -----------------------------------------------------------------
        # Step 3: Strict ambiguity enforcement for genuine ambiguity
        # -----------------------------------------------------------------
        if len(valid_candidates) > 1:
            raise VisualPerceptionError(
                "TARGET_AMBIGUOUS",
                f"Multiple viable candidates found ({len(valid_candidates)}). Ambiguity resolution not currently implemented.",
            )

        selected = valid_candidates[0]
        logger.debug(f"Selected target {selected.target_id} with confidence {selected.confidence}.")
        return selected


target_selection_service = TargetSelectionService()


