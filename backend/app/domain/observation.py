from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from pydantic import BaseModel, Field

from app.domain.entities import ScreenPoint, TriState
from app.domain.visual import VisualObservation, VisualTarget
from app.environment.models import WindowEntity
from app.interaction.models import UIElement

MULTIMODAL_SCHEMA_VERSION = "1.0"


class CoordinateSpace(str, Enum):
    """Explicitly distinguished coordinate domains."""
    IMAGE_LOCAL = "IMAGE_LOCAL"            # 2D pixel space [0, width) x [0, height) of captured bitmap
    WINDOW_RELATIVE = "WINDOW_RELATIVE"    # Pixel offset relative to window top-left (x - win_x, y - win_y)
    VIRTUAL_SCREEN = "VIRTUAL_SCREEN"      # Physical OS multi-monitor virtual screen coordinates
    DPI_LOGICAL = "DPI_LOGICAL"            # Logical application units scaled by DPI factor


class CoordinateTransformError(Exception):
    """Raised when coordinate transformation violates boundaries or invariant rules."""
    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code}] {message}")


class BoundingBox(BaseModel):
    """
    Validated 2D bounding rectangle in a specific, declared coordinate space.
    """
    x: float = Field(description="Left coordinate in declared coordinate_space")
    y: float = Field(description="Top coordinate in declared coordinate_space")
    width: float = Field(gt=0, description="Width of bounding box")
    height: float = Field(gt=0, description="Height of bounding box")
    coordinate_space: CoordinateSpace = Field(default=CoordinateSpace.IMAGE_LOCAL)

    @property
    def right(self) -> float:
        return self.x + self.width

    @property
    def bottom(self) -> float:
        return self.y + self.height

    @property
    def center(self) -> Tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)

    def as_tuple(self) -> Tuple[int, int, int, int]:
        return (int(round(self.x)), int(round(self.y)), int(round(self.width)), int(round(self.height)))


def image_to_virtual_screen(
    image_x: float,
    image_y: float,
    virtual_offset_x: int,
    virtual_offset_y: int,
    capture_width: int,
    capture_height: int,
    validate: bool = True,
) -> ScreenPoint:
    """
    Transforms image-local pixel coordinate to physical virtual-screen coordinates:
        screen_x = image_x + virtual_offset_x
        screen_y = image_y + virtual_offset_y
    """
    if validate:
        if image_x < 0 or image_x >= capture_width or image_y < 0 or image_y >= capture_height:
            raise CoordinateTransformError(
                "OUT_OF_IMAGE_BOUNDS",
                f"Image coordinate ({image_x}, {image_y}) is outside capture dimensions {capture_width}x{capture_height}",
                {"image_x": image_x, "image_y": image_y, "width": capture_width, "height": capture_height},
            )
    return ScreenPoint(
        x=int(round(image_x + virtual_offset_x)),
        y=int(round(image_y + virtual_offset_y)),
    )


def virtual_screen_to_image(
    screen_x: float,
    screen_y: float,
    virtual_offset_x: int,
    virtual_offset_y: int,
    capture_width: int,
    capture_height: int,
    validate: bool = True,
) -> Tuple[int, int]:
    """
    Transforms physical virtual-screen coordinate to image-local pixel coordinate:
        image_x = screen_x - virtual_offset_x
        image_y = screen_y - virtual_offset_y
    """
    img_x = int(round(screen_x - virtual_offset_x))
    img_y = int(round(screen_y - virtual_offset_y))
    if validate:
        if img_x < 0 or img_x >= capture_width or img_y < 0 or img_y >= capture_height:
            raise CoordinateTransformError(
                "OUT_OF_IMAGE_BOUNDS",
                f"Virtual screen coordinate ({screen_x}, {screen_y}) maps to image pixel ({img_x}, {img_y}) "
                f"outside capture dimensions {capture_width}x{capture_height}",
                {"screen_x": screen_x, "screen_y": screen_y, "img_x": img_x, "img_y": img_y},
            )
    return (img_x, img_y)


def virtual_screen_to_window(
    screen_x: float,
    screen_y: float,
    window_bounds: Tuple[int, int, int, int],
    validate: bool = False,
) -> Tuple[float, float]:
    """
    Transforms physical virtual-screen coordinate to window-relative coordinate:
        rel_x = screen_x - win_x
        rel_y = screen_y - win_y
    """
    win_x, win_y, win_w, win_h = window_bounds
    rel_x = screen_x - win_x
    rel_y = screen_y - win_y
    if validate:
        if rel_x < 0 or rel_x > win_w or rel_y < 0 or rel_y > win_h:
            raise CoordinateTransformError(
                "OUT_OF_WINDOW_BOUNDS",
                f"Screen coordinate ({screen_x}, {screen_y}) falls outside window bounds {window_bounds}",
                {"screen_x": screen_x, "screen_y": screen_y, "window_bounds": window_bounds},
            )
    return (rel_x, rel_y)


def window_to_virtual_screen(
    rel_x: float,
    rel_y: float,
    window_bounds: Tuple[int, int, int, int],
) -> ScreenPoint:
    """
    Transforms window-relative coordinate to physical virtual-screen coordinate:
        screen_x = win_x + rel_x
        screen_y = win_y + rel_y
    """
    win_x, win_y, _, _ = window_bounds
    return ScreenPoint(x=int(round(win_x + rel_x)), y=int(round(win_y + rel_y)))


def transform_bbox(
    bbox: BoundingBox,
    target_space: CoordinateSpace,
    virtual_offset_x: int = 0,
    virtual_offset_y: int = 0,
    capture_width: int = 0,
    capture_height: int = 0,
    window_bounds: Optional[Tuple[int, int, int, int]] = None,
) -> BoundingBox:
    """
    Transforms a BoundingBox from its current coordinate_space to target_space without silent clamping.
    """
    if bbox.coordinate_space == target_space:
        return bbox.model_copy()

    # Step 1: Normalize source to VIRTUAL_SCREEN intermediate
    if bbox.coordinate_space == CoordinateSpace.VIRTUAL_SCREEN:
        vx, vy = bbox.x, bbox.y
    elif bbox.coordinate_space == CoordinateSpace.IMAGE_LOCAL:
        vx = bbox.x + virtual_offset_x
        vy = bbox.y + virtual_offset_y
    elif bbox.coordinate_space == CoordinateSpace.WINDOW_RELATIVE:
        if not window_bounds:
            raise CoordinateTransformError(
                "MISSING_WINDOW_BOUNDS",
                "Cannot transform from WINDOW_RELATIVE without window_bounds.",
            )
        vx = window_bounds[0] + bbox.x
        vy = window_bounds[1] + bbox.y
    else:
        raise CoordinateTransformError(
            "UNSUPPORTED_COORDINATE_SPACE",
            f"Transformation from {bbox.coordinate_space} is not supported.",
        )

    # Step 2: Convert VIRTUAL_SCREEN to target_space
    if target_space == CoordinateSpace.VIRTUAL_SCREEN:
        tx, ty = vx, vy
    elif target_space == CoordinateSpace.IMAGE_LOCAL:
        tx = vx - virtual_offset_x
        ty = vy - virtual_offset_y
    elif target_space == CoordinateSpace.WINDOW_RELATIVE:
        if not window_bounds:
            raise CoordinateTransformError(
                "MISSING_WINDOW_BOUNDS",
                "Cannot transform to WINDOW_RELATIVE without window_bounds.",
            )
        tx = vx - window_bounds[0]
        ty = vy - window_bounds[1]
    else:
        raise CoordinateTransformError(
            "UNSUPPORTED_COORDINATE_SPACE",
            f"Transformation to {target_space} is not supported.",
        )

    return BoundingBox(
        x=tx,
        y=ty,
        width=bbox.width,
        height=bbox.height,
        coordinate_space=target_space,
    )


class AudioUtteranceContext(BaseModel):
    """
    Captures temporal and session metadata of speech utterances for cross-modal alignment.
    """
    utterance_id: str = Field(description="Unique identifier for the speech utterance")
    session_id: Optional[str] = Field(default=None, description="Conversation session ID")
    client_timestamp_ms: Optional[float] = Field(default=None, description="Client-side timestamp in ms")
    start_time_utc: datetime = Field(description="Start time of user speech in UTC")
    end_time_utc: Optional[datetime] = Field(default=None, description="End time of user speech in UTC")
    transcript_text: str = Field(default="", description="Recognized transcript from STT provider")
    clock_domain: str = Field(default="CLIENT_MONOTONIC", description="Source clock domain reference")
    aligned_observation_id: Optional[str] = Field(default=None, description="ID of MultimodalObservation active at utterance onset")


class PerceptualDiffResult(BaseModel):
    """
    Structured outcome of frame differencing between consecutive visual captures.
    """
    has_changed: bool = Field(description="True if visual mutation exceeds threshold")
    change_ratio: float = Field(ge=0.0, le=1.0, description="Proportion of pixels altered [0.0, 1.0]")
    damage_region: Optional[Tuple[int, int, int, int]] = Field(
        default=None,
        description="(x, y, width, height) bounding box of changed region in image space",
    )
    diff_hash: str = Field(default="", description="Deterministic perceptual digest of delta")
    ocr_suppressed: bool = Field(default=False, description="True if redundant OCR was avoided")
    forced_refresh: bool = Field(default=False, description="True if diff was overridden by explicit refresh")
    duration_ms: float = Field(default=0.0, description="Time taken to compute perceptual diff in ms")


class TrackedTarget(BaseModel):
    """
    A visual element tracked across consecutive observations with spatial drift and occlusion status.
    """
    target_id: str = Field(description="Stable identifier for the tracked target across frames")
    label: str = Field(description="Semantic label or OCR text")
    target_type: str = Field(default="text", description="Target element type")
    confidence: float = Field(ge=0.0, le=1.0, description="Detection / tracking confidence")
    current_bbox: BoundingBox = Field(description="Latest bounding box in declared coordinate space")
    initial_bbox: BoundingBox = Field(description="Initial bounding box when first grounded")
    source_observation_id: str = Field(description="Observation ID where target was first identified")
    last_verified_observation_id: str = Field(description="Observation ID where target was most recently verified")
    movement_px: float = Field(default=0.0, description="Total Euclidean drift in pixels from initial position")
    is_occluded: bool = Field(default=False, description="True if target is obscured by overlapping window/popup")
    is_stale: bool = Field(default=False, description="True if target is beyond TTL or missing from latest frame")
    target_window_hwnd: Optional[int] = Field(default=None, description="Owning window handle if known")
    semantic_attributes: Dict[str, Any] = Field(default_factory=dict, description="Metadata and OCR properties")


class MultimodalObservation(BaseModel):
    """
    Canonical unified multimodal observation snapshot uniting screen capture,
    WinRT OCR detections, active window geometry, UI hierarchy, and audio context.
    """
    observation_id: str = Field(description="Unique identifier for this multimodal observation")
    schema_version: str = Field(default=MULTIMODAL_SCHEMA_VERSION)
    captured_at_utc: datetime = Field(description="Authoritative UTC capture timestamp")
    visual: VisualObservation = Field(description="Low-level visual capture metadata")
    is_full_virtual_desktop: bool = Field(default=True, description="True if capture spans all active displays")
    capture_region: Tuple[int, int, int, int] = Field(
        description="(x, y, width, height) bounding rectangle in virtual screen coordinates"
    )
    text_detections: List[VisualTarget] = Field(default_factory=list, description="OCR text candidates")
    active_window: Optional[WindowEntity] = Field(default=None, description="Foreground window entity at capture time")
    ui_elements: Optional[List[UIElement]] = Field(default=None, description="UIAutomation element tree if available")
    audio_context: Optional[AudioUtteranceContext] = Field(default=None, description="Associated audio/voice context")
    spatial_hash: str = Field(default="", description="Deterministic spatial layout digest")
    diff_from_previous: Optional[PerceptualDiffResult] = Field(default=None, description="Delta from predecessor")
    modality_availability: Dict[str, bool] = Field(default_factory=dict, description="Availability flags per modality")
