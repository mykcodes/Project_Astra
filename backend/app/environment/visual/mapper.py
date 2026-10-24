from typing import Tuple
from app.domain.entities import ScreenPoint
from app.domain.visual import VisualObservation, VisualCaptureError
from app.environment.visual.tracker import interaction_tracker
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class VisualCoordinateMapper:
    """
    Translates image pixel coordinates into the canonical ScreenPoint physical coordinate space.
    Enforces staleness invalidation.
    """
    
    def map_to_screen_point(self, observation: VisualObservation, image_x: int, image_y: int) -> ScreenPoint:
        """
        Maps a 2D pixel coordinate from a full-virtual-screen capture to a physical ScreenPoint.
        """
        # 1. Freshness Check
        last_interaction = interaction_tracker.get_last_interaction()
        obs_time = observation.captured_at
        if getattr(last_interaction, "tzinfo", None) is not None and getattr(obs_time, "tzinfo", None) is None:
            from datetime import timezone
            obs_time = obs_time.replace(tzinfo=timezone.utc)
        elif getattr(last_interaction, "tzinfo", None) is None and getattr(obs_time, "tzinfo", None) is not None:
            from datetime import timezone
            last_interaction = last_interaction.replace(tzinfo=timezone.utc)

        if last_interaction > obs_time:
            raise VisualCaptureError(
                "STALE_OBSERVATION",
                f"Observation {observation.observation_id} is stale. "
                f"A physical interaction occurred at {last_interaction.isoformat()} "
                f"which is after the capture timestamp {obs_time.isoformat()}."
            )
            
        # 2. Bounds Check (optional but good practice)
        if image_x < 0 or image_x >= observation.width or image_y < 0 or image_y >= observation.height:
            logger.warning(
                f"Mapping out-of-bounds image pixel ({image_x}, {image_y}) "
                f"for observation of size {observation.width}x{observation.height}."
            )
            
        # 3. Coordinate Transformation Invariant
        # ScreenPoint = (ImagePixel.x + virtual_offset_x, ImagePixel.y + virtual_offset_y)
        screen_x = image_x + observation.virtual_offset_x
        screen_y = image_y + observation.virtual_offset_y
        
        return ScreenPoint(x=screen_x, y=screen_y)

visual_mapper = VisualCoordinateMapper()
