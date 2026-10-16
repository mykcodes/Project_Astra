from app.domain.visual import VisualTarget, GroundedTarget, VisualObservation, VisualPerceptionError
from app.environment.visual.mapper import visual_mapper
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class TargetGroundingService:
    """
    Translates a single semantic VisualTarget into a physical OS coordinate (ScreenPoint).
    Responsibility: "Where exactly is the selected target in physical OS screen space?"
    """
    
    def ground(self, target: VisualTarget, observation: VisualObservation) -> GroundedTarget:
        """
        Grounds the target.
        Enforces provenance, geometry bounds, and staleness validation.
        """
        # 1. Provenance / Mismatch check
        if target.source_observation_id != observation.observation_id:
            raise VisualPerceptionError(
                "TARGET_OBSERVATION_MISMATCH",
                f"Target provenance mismatch. Target belongs to {target.source_observation_id}, "
                f"but grounding was requested against {observation.observation_id}."
            )
            
        # 2. Anchor calculation (deterministic center for B.3.1)
        anchor_x = target.bbox_x + (target.bbox_width // 2)
        anchor_y = target.bbox_y + (target.bbox_height // 2)
        
        # 3. Geometry validation (No silent clamping)
        # B.2 image space domain: [0, width), [0, height)
        if not (0 <= anchor_x < observation.width):
            raise VisualPerceptionError(
                "INVALID_TARGET_GEOMETRY",
                f"Computed anchor X ({anchor_x}) falls outside observation bounds [0, {observation.width})."
            )
            
        if not (0 <= anchor_y < observation.height):
            raise VisualPerceptionError(
                "INVALID_TARGET_GEOMETRY",
                f"Computed anchor Y ({anchor_y}) falls outside observation bounds [0, {observation.height})."
            )
            
        # 4. Physical OS Coordinate Grounding
        # Delegate to the authoritative B.2 mapper.
        # This implicitly performs the interaction_tracker staleness check.
        try:
            screen_point = visual_mapper.map_to_screen_point(observation, anchor_x, anchor_y)
        except Exception as e:
            # If the underlying mapper raised STALE_OBSERVATION, propagate it or wrap it
            if hasattr(e, 'code') and e.code == "STALE_OBSERVATION":
                raise  # Let staleness flow transparently
            raise VisualPerceptionError("GROUNDING_FAILED", f"Coordinate mapping failed: {e}")
            
        logger.debug(f"Grounded target {target.target_id} to {screen_point}.")
        
        # 5. Return GroundedTarget
        return GroundedTarget(
            target=target,
            source_observation_id=observation.observation_id,
            anchor_point=screen_point
        )

target_grounding_service = TargetGroundingService()
