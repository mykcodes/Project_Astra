import time
import uuid
import sys
from typing import Dict, Any, List, Optional
from app.core.logging.logger import get_logger
from app.interaction.models import UIElement, UIAutomationSupport, BoundingRectangle
from app.interaction.capability_manager import capability_manager

logger = get_logger(__name__)

# Only import uiautomation on Windows, to avoid crashing tests on Linux
try:
    import uiautomation as auto
    # auto.SetGlobalSearchTimeout(2.0) # Prevent long hangs
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

class UIEngine:
    def __init__(self):
        self._tree_cache: Dict[int, Dict[str, Any]] = {}
        self.last_discovery_latency: float = 0.0
        
    def _create_bounding_rect(self, rect) -> Optional[BoundingRectangle]:
        if not rect:
            return None
        try:
            return BoundingRectangle(
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom
            )
        except AttributeError:
            return None

    def _extract_patterns(self, control) -> List[str]:
        patterns = []
        try:
            # Check supported patterns in uiautomation
            if hasattr(control, 'InvokePattern') and control.InvokePattern: patterns.append("Invoke")
            if hasattr(control, 'ValuePattern') and control.ValuePattern: patterns.append("Value")
            if hasattr(control, 'SelectionItemPattern') and control.SelectionItemPattern: patterns.append("SelectionItem")
            if hasattr(control, 'TogglePattern') and control.TogglePattern: patterns.append("Toggle")
            if hasattr(control, 'ExpandCollapsePattern') and control.ExpandCollapsePattern: patterns.append("ExpandCollapse")
            if hasattr(control, 'ScrollPattern') and control.ScrollPattern: patterns.append("Scroll")
            if hasattr(control, 'WindowPattern') and control.WindowPattern: patterns.append("Window")
        except Exception:
            pass
        return patterns

    def _map_control_to_element(self, control, parent_id: Optional[str] = None) -> UIElement:
        runtime_id = str(uuid.uuid4()) # For internal reference tracking
        try:
            name = control.Name
        except Exception:
            name = ""
            
        try:
            auto_id = control.AutomationId
        except Exception:
            auto_id = ""
            
        try:
            class_name = control.ClassName
        except Exception:
            class_name = ""
            
        try:
            control_type = control.ControlTypeName
        except Exception:
            control_type = "Unknown"
            
        try:
            pid = control.ProcessId
        except Exception:
            pid = 0
            
        try:
            hwnd = control.NativeWindowHandle
        except Exception:
            hwnd = 0

        try:
            framework_id = control.FrameworkId
        except Exception:
            framework_id = ""

        # Safe attribute extraction
        def safe_get(attr, default):
            try:
                return getattr(control, attr)
            except Exception:
                return default

        return UIElement(
            runtime_id=runtime_id,
            name=name,
            control_type=control_type,
            automation_id=auto_id,
            class_name=class_name,
            framework_id=framework_id,
            process_id=pid,
            window_handle=hwnd,
            parent_id=parent_id,
            enabled=safe_get("IsEnabled", True),
            visible=safe_get("IsOffscreen", False) is False,
            focused=safe_get("HasKeyboardFocus", False),
            selected=safe_get("IsSelected", False) if hasattr(control, "IsSelected") else False,
            bounding_rectangle=self._create_bounding_rect(safe_get("BoundingRectangle", None)),
            supported_patterns=self._extract_patterns(control)
        )

    def check_capability(self, hwnd: int) -> Dict[str, Any]:
        return capability_manager.inspect_window(hwnd)

    def invalidate_cache(self, hwnd: Optional[int] = None):
        if hwnd is None:
            self._tree_cache.clear()
        elif hwnd in self._tree_cache:
            del self._tree_cache[hwnd]

    def discover_ui_tree(self, hwnd: int, max_depth: int = 5, force_refresh: bool = False) -> List[UIElement]:
        if not HAS_UIA:
            return []
            
        now = time.time()
        
        if not force_refresh and hwnd in self._tree_cache:
            cache_entry = self._tree_cache[hwnd]
            # 5 second TTL for tree cache
            if now - cache_entry["timestamp"] < 5.0:
                return cache_entry["elements"]
                
        try:
            window = auto.WindowControl(searchDepth=1, Handle=hwnd)
            if not window.Exists(0.5):
                return []
                
            elements = []
            
            # Recursive bounded traversal
            def traverse(control, parent_id, depth):
                if depth > max_depth:
                    return
                try:
                    children = control.GetChildren()
                except Exception:
                    children = []
                    
                for child in children:
                    element = self._map_control_to_element(child, parent_id=parent_id)
                    elements.append(element)
                    traverse(child, element.runtime_id, depth + 1)
                    
            traverse(window, None, 1)
            
            latency = time.time() - now
            self.last_discovery_latency = latency
            self._tree_cache[hwnd] = {
                "timestamp": now,
                "elements": elements
            }
            return elements
            
        except Exception as e:
            logger.error(f"UI Tree discovery failed for {hwnd}: {e}")
            return []
            
ui_engine = UIEngine()
