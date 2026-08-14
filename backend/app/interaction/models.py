from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional
import time
import uuid

class UIAutomationSupport(str, Enum):
    FULL = "UI_AUTOMATION_FULL"
    PARTIAL = "UI_AUTOMATION_PARTIAL"
    UNAVAILABLE = "UI_AUTOMATION_UNAVAILABLE"
    UNKNOWN = "UNKNOWN"

class InteractionAction(str, Enum):
    CLICK = "CLICK"
    DOUBLE_CLICK = "DOUBLE_CLICK"
    RIGHT_CLICK = "RIGHT_CLICK"
    TYPE_TEXT = "TYPE_TEXT"
    PRESS_KEY = "PRESS_KEY"
    HOTKEY = "HOTKEY"
    SCROLL = "SCROLL"
    DRAG = "DRAG"
    FOCUS = "FOCUS"
    MOVE = "MOVE"
    RESIZE = "RESIZE"
    MINIMIZE = "MINIMIZE"
    MAXIMIZE = "MAXIMIZE"
    RESTORE = "RESTORE"

class InteractionMethod(str, Enum):
    UIA_INVOKE = "UIA_INVOKE"
    UIA_VALUE = "UIA_VALUE"
    UIA_SELECT = "UIA_SELECT"
    UIA_SCROLL = "UIA_SCROLL"
    WIN32_MESSAGE = "WIN32_MESSAGE"
    KEYBOARD_INJECTION = "KEYBOARD_INJECTION"
    MOUSE_INJECTION = "MOUSE_INJECTION"
    COORDINATE_FALLBACK = "COORDINATE_FALLBACK"

class InteractionErrorCategory(str, Enum):
    APPLICATION_NOT_FOUND = "APPLICATION_NOT_FOUND"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    UI_ELEMENT_NOT_FOUND = "UI_ELEMENT_NOT_FOUND"
    UI_ELEMENT_AMBIGUOUS = "UI_ELEMENT_AMBIGUOUS"
    UI_AUTOMATION_UNAVAILABLE = "UI_AUTOMATION_UNAVAILABLE"
    TARGET_DISABLED = "TARGET_DISABLED"
    TARGET_NOT_VISIBLE = "TARGET_NOT_VISIBLE"
    FOCUS_FAILED = "FOCUS_FAILED"
    INPUT_FAILED = "INPUT_FAILED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    TIMEOUT = "TIMEOUT"
    UNSUPPORTED_APPLICATION = "UNSUPPORTED_APPLICATION"
    MODAL_BLOCKED = "MODAL_BLOCKED"
    STALE_OBSERVATION = "STALE_OBSERVATION"
    APPLICATION_NOT_READY = "APPLICATION_NOT_READY"
    TEXT_VERIFICATION_FAILED = "TEXT_VERIFICATION_FAILED"
    INTERACTION_UNSUPPORTED = "INTERACTION_UNSUPPORTED"
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"

@dataclass
class BoundingRectangle:
    left: int
    top: int
    right: int
    bottom: int
    
    @property
    def width(self) -> int:
        return self.right - self.left
        
    @property
    def height(self) -> int:
        return self.bottom - self.top
        
    @property
    def center_x(self) -> int:
        return self.left + (self.width // 2)
        
    @property
    def center_y(self) -> int:
        return self.top + (self.height // 2)

@dataclass
class UIElementState:
    """Represents the instantaneous state of a UIElement"""
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    selected: bool = False
    value_available: bool = False
    value: Optional[str] = None # Masked if sensitive

@dataclass
class UIElement:
    """Represents a discovered UI element with robust identity for re-resolution."""
    runtime_id: str
    name: str
    control_type: str
    automation_id: str
    class_name: str
    framework_id: str
    process_id: int
    window_handle: int
    role: str = ""
    parent_id: Optional[str] = None
    children_ids: List[str] = field(default_factory=list)
    state: UIElementState = field(default_factory=UIElementState)
    bounding_rectangle: Optional[BoundingRectangle] = None
    supported_patterns: List[str] = field(default_factory=list)
    confidence: float = 1.0

@dataclass
class UIWindow:
    """Represents a window structure for Observation"""
    hwnd: int
    process_id: int
    application_identity: str
    framework: str
    title: str
    role: str
    bounds: Optional[BoundingRectangle]
    monitor: int
    z_order: int
    is_main_window: bool
    is_modal: bool
    is_popup: bool
    is_minimized: bool
    is_maximized: bool
    is_foreground: bool
    owner_hwnd: Optional[int] = None
    parent_hwnd: Optional[int] = None

@dataclass
class UIObservation:
    """A canonical snapshot of UI state at a given time."""
    observation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    window: UIWindow = None
    elements: Dict[str, UIElement] = field(default_factory=dict)
    foreground_hwnd: int = 0
    state_hash: str = ""
    valid: bool = True

@dataclass
class UIChange:
    """Represents a structural or state transition between two observations."""
    change_type: str  # e.g., 'FOCUS_CHANGED', 'VALUE_CHANGED', 'WINDOW_OPENED', 'CONTROL_APPEARED'
    element_id: Optional[str] = None
    old_value: Any = None
    new_value: Any = None
    description: str = ""

@dataclass
class UIQueryResult:
    """Represents the result of semantic target resolution."""
    query: str
    status: str # RESOLVED, AMBIGUOUS, NOT_FOUND
    candidate_count: int
    selected_candidate: Optional[UIElement] = None
    confidence: float = 0.0
    matching_properties: List[str] = field(default_factory=list)
    ambiguous_candidates: List[str] = field(default_factory=list)
    observation_id: str = ""

@dataclass
class UIInteractionContext:
    """Short-lived interaction queue memory."""
    foreground_application: str = ""
    foreground_window: int = 0
    active_modal: Optional[int] = None
    current_ui_target: Optional[str] = None
    previous_ui_target: Optional[str] = None
    last_successful_interaction: Optional[str] = None
    last_failed_target: Optional[str] = None
    last_observed_state: Optional[UIObservation] = None
    interaction_sequence: List[str] = field(default_factory=list)

@dataclass
class WindowTarget:
    """Legacy target window. Retained for compatibility where needed."""
    hwnd: int
    process_id: int
    title: str
    automation_support: UIAutomationSupport = UIAutomationSupport.UNKNOWN

@dataclass
class InteractionTarget:
    """Represents the object ASTRA intends to interact with."""
    window: WindowTarget
    element: Optional[UIElement] = None
    x_offset: Optional[int] = None
    y_offset: Optional[int] = None

@dataclass
class InteractionResult:
    """Strict contract for interaction results."""
    success: bool
    action: str
    target_name: str
    target_resolved: bool
    interaction_method: Optional[str] = None
    verified: bool = False
    attempts: int = 1
    state_before: Dict[str, Any] = field(default_factory=dict)
    state_after: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self):
        return {
            "success": self.success,
            "action": self.action,
            "target": self.target_name,
            "target_resolved": self.target_resolved,
            "interaction_method": self.interaction_method,
            "verified": self.verified,
            "attempts": self.attempts,
            "state_before": self.state_before,
            "state_after": self.state_after,
            "error": self.error,
            "diagnostics": self.diagnostics
        }
