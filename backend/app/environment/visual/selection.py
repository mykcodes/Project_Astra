from typing import List
from app.domain.visual import VisualTarget, VisualPerceptionError
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class TargetSelectionService:
    """
    Selects a single visual target from a pool of candidates based on semantic and confidence policies.
    Responsibility: "Which candidate, if any, satisfies the semantic request?"
    """
    
    def select_target(self, candidates: List[VisualTarget], min_confidence: float = 0.5) -> VisualTarget:
        """
        Evaluates candidates and selects exactly one target.
        Fails structured if ambiguous, not found, or confidence is too low.
        """
        if not candidates:
            raise VisualPerceptionError("TARGET_NOT_FOUND", "Perception returned no candidates.")
            
        # Filter by confidence
        valid_candidates = [c for c in candidates if c.confidence >= min_confidence]
        
        if not valid_candidates:
            # We had candidates, but none met the threshold
            highest_conf = max(candidates, key=lambda x: x.confidence)
            raise VisualPerceptionError(
                "TARGET_CONFIDENCE_TOO_LOW", 
                f"Candidates found, but highest confidence ({highest_conf.confidence}) is below threshold ({min_confidence})."
            )
            
        # Ambiguity check
        if len(valid_candidates) > 1:
            raise VisualPerceptionError(
                "TARGET_AMBIGUOUS", 
                f"Multiple viable candidates found ({len(valid_candidates)}). Ambiguity resolution not currently implemented."
            )
            
        selected = valid_candidates[0]
        logger.debug(f"Selected target {selected.target_id} with confidence {selected.confidence}.")
        return selected

target_selection_service = TargetSelectionService()
