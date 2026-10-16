from pydantic import BaseModel, Field
from datetime import datetime

class VisualObservation(BaseModel):
    """
    Immutable, point-in-time metadata for a visual observation.
    Does NOT contain the raw pixel blob.
    """
    observation_id: str
    captured_at: datetime
    width: int
    height: int
    virtual_offset_x: int
    virtual_offset_y: int
    pixel_format: str
    image_reference: str = Field(description="Opaque identifier owned by capture subsystem. Do NOT assume it is a filesystem path.")

# FUTURE CONTRACT ONLY - NOT IMPLEMENTED IN B.2
class VisualTarget(BaseModel):
    """
    A semantic visual target derived from an observation.
    Geometry is strictly in IMAGE coordinates [0, observation.width) x [0, observation.height).
    """
    target_id: str = Field(description="Stable identifier for the target within the observation context.")
    label: str = Field(description="Semantic label or recognized text.")
    target_type: str = Field(description="Category of the target (e.g., 'text', 'icon', 'button').")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection confidence between 0.0 and 1.0.")
    bbox_x: int = Field(ge=0, description="Image-space bounding box left coordinate.")
    bbox_y: int = Field(ge=0, description="Image-space bounding box top coordinate.")
    bbox_width: int = Field(gt=0, description="Image-space bounding box width.")
    bbox_height: int = Field(gt=0, description="Image-space bounding box height.")
    source_observation_id: str = Field(description="ID of the VisualObservation this target was derived from.")
    semantic_attributes: dict = Field(default_factory=dict, description="Additional properties.")

from app.domain.entities import ScreenPoint

class GroundedTarget(BaseModel):
    """
    A selected VisualTarget securely mapped to physical screen space.
    """
    target: VisualTarget
    source_observation_id: str
    anchor_point: ScreenPoint

class VisualError(Exception):
    """Base exception for all visual subsystem failures."""
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")

class VisualCaptureError(VisualError):
    """Structured error for visual capture failures."""
    pass

class VisualPerceptionError(VisualError):
    """Structured error for visual perception, selection, and grounding failures."""
    pass
