import time
from typing import Dict, Any, Optional
from app.core.logging.logger import get_logger
from app.interaction.models import UIElement, InteractionMethod

logger = get_logger(__name__)

try:
    import uiautomation as auto
    import win32gui
    import win32api
    import win32con
    HAS_INPUT = True
except ImportError:
    HAS_INPUT = False

class InputEngine:
    """Handles semantic interaction primitives using the fallback hierarchy."""
    
    def click(self, element: UIElement) -> Dict[str, Any]:
        if not HAS_INPUT:
            return {"success": False, "reason": "Input dependencies missing", "method": None}
            
        # 1. UI Automation InvokePattern
        if "Invoke" in element.supported_patterns:
            try:
                control = auto.ControlFromHandle(element.window_handle) if element.window_handle else None
                # We need the actual control object, but since we cache UIElements, we re-bind by RuntimeId
                # For safety and speed in this wrapper, if we can't find it quickly, we fall back.
                if element.runtime_id:
                    # In a full implementation, we'd look up the control by RuntimeId
                    pass 
                    
                # To invoke deterministically, uiautomation requires the object.
                # Assuming the caller guarantees the element is still valid, we can use coordinate fallback 
                # OR we could have cached the native object. Since caching native COM objects is dangerous,
                # we do a quick re-resolve or use the UIA coordinate click if safe.
                pass
            except Exception as e:
                logger.warning(f"InvokePattern failed: {e}")
                
        # 4. Mouse Injection / Coordinate Fallback (Requires verified bounding rect)
        if element.bounding_rectangle and element.visible and element.enabled:
            x = element.bounding_rectangle.center_x
            y = element.bounding_rectangle.center_y
            try:
                auto.Click(x, y)
                return {"success": True, "method": InteractionMethod.COORDINATE_FALLBACK.value}
            except Exception as e:
                return {"success": False, "reason": f"Click failed: {e}", "method": InteractionMethod.COORDINATE_FALLBACK.value}
                
        return {"success": False, "reason": "No supported click method or element not visible", "method": None}

    def type_text(self, element: UIElement, text: str) -> Dict[str, Any]:
        if not HAS_INPUT:
            return {"success": False, "reason": "Input dependencies missing"}
            
        value_verified = False
        extracted_value = None
        
        # 1. UI Automation ValuePattern (Safe, semantic)
        if "Value" in element.supported_patterns:
            try:
                control = auto.ControlFromHandle(element.window_handle) if element.window_handle else None
                # In full COM automation we'd lookup by RuntimeID, but here we fallback to coordinate + sendkeys
                # and then try to read the ValuePattern out if possible. Since we're wrapping uiautomation:
                pass
            except Exception as e:
                logger.warning(f"ValuePattern interaction failed: {e}")
                
        # 3. Keyboard Injection (Requires focus)
        if element.bounding_rectangle and element.visible:
            x = element.bounding_rectangle.center_x
            y = element.bounding_rectangle.center_y
            try:
                auto.Click(x, y)
                time.sleep(0.1)
                auto.SendKeys(text)
                
                # Attempt to extract the value back out for verification
                try:
                    # Very expensive to re-traverse, so we'll just check if it's the focused element
                    focused = auto.GetFocusedControl()
                    if hasattr(focused, 'GetValuePattern'):
                        val_pattern = focused.GetValuePattern()
                        if val_pattern:
                            extracted_value = val_pattern.Value
                            if text in extracted_value:
                                value_verified = True
                except Exception:
                    pass
                    
                return {
                    "success": True, 
                    "method": InteractionMethod.KEYBOARD_INJECTION.value,
                    "extracted_value": extracted_value,
                    "value_verified": value_verified
                }
            except Exception as e:
                return {"success": False, "reason": f"Type failed: {e}"}
                
        return {"success": False, "reason": "Cannot type: Element not visible or resolvable"}

    def press_key(self, key: str) -> Dict[str, Any]:
        """Presses a special key (ENTER, TAB, ESC, etc)."""
        if not HAS_INPUT:
            return {"success": False, "reason": "Input dependencies missing"}
            
        key_map = {
            "ENTER": "{Enter}",
            "ESC": "{Esc}",
            "TAB": "{Tab}",
            "UP": "{Up}",
            "DOWN": "{Down}",
            "LEFT": "{Left}",
            "RIGHT": "{Right}",
            "BACKSPACE": "{Backspace}",
            "DELETE": "{Delete}"
        }
        
        mapped = key_map.get(key.upper())
        if not mapped:
            return {"success": False, "reason": f"Unsupported key: {key}"}
            
        try:
            auto.SendKeys(mapped)
            return {"success": True, "method": InteractionMethod.KEYBOARD_INJECTION.value}
        except Exception as e:
            return {"success": False, "reason": f"Key press failed: {e}"}

input_engine = InputEngine()
