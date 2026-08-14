from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional

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
    parent_id: Optional[str] = None
    enabled: bool = True
    visible: bool = True
    focused: bool = False
    selected: bool = False
    bounding_rectangle: Optional[BoundingRectangle] = None
    supported_patterns: List[str] = field(default_factory=list)
    confidence: float = 1.0

@dataclass
class WindowTarget:
    """Represents a verified target window."""
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
