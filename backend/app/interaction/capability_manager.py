from typing import Dict, Any, List
from app.interaction.models import UIAutomationSupport
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

try:
    import uiautomation as auto
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

class CapabilityManager:
    """Detects deterministic UI capabilities and decides fallback strategies (e.g. for Electron)."""
    
    def inspect_window(self, hwnd: int) -> Dict[str, Any]:
        """Deeply inspects the window to determine its interaction capabilities."""
        if not HAS_UIA:
            return {
                "status": UIAutomationSupport.UNAVAILABLE.value,
                "framework_id": "Unknown",
                "keyboard_navigation_viable": False,
                "reason": "uiautomation module not available"
            }
            
        try:
            window = auto.WindowControl(searchDepth=1, Handle=hwnd)
            if not window.Exists(0.5):
                return {
                    "status": UIAutomationSupport.UNAVAILABLE.value,
                    "framework_id": "Unknown",
                    "keyboard_navigation_viable": False,
                    "reason": "Window HWND not found"
                }
                
            framework_id = ""
            try:
                framework_id = window.FrameworkId
            except Exception:
                pass
                
            children = window.GetChildren()
            
            # If no children at all, UIA is dead
            if not children:
                return {
                    "status": UIAutomationSupport.UNAVAILABLE.value,
                    "framework_id": framework_id,
                    "keyboard_navigation_viable": True, # Might still accept blind keyboard input
                    "reason": "Window exposes no UIA children"
                }
                
            # Check for Electron/Chromium monolithic render surface
            # Typically class is Chrome_WidgetWin_1 or similar, and it has 1 Document child
            if len(children) == 1 and children[0].ControlTypeName in ("DocumentControl", "CustomControl", "PaneControl"):
                sub_children = children[0].GetChildren()
                if not sub_children:
                    return {
                        "status": UIAutomationSupport.PARTIAL.value,
                        "framework_id": framework_id or "Electron/Chromium",
                        "keyboard_navigation_viable": True,
                        "reason": "Window exposes a monolithic render surface without detailed controls (Accessibility likely disabled)"
                    }
                    
            # Check for standard Win32 / WPF / full UIA applications
            return {
                "status": UIAutomationSupport.FULL.value,
                "framework_id": framework_id,
                "keyboard_navigation_viable": True,
                "reason": "UIA tree available and populated"
            }
            
        except Exception as e:
            return {
                "status": UIAutomationSupport.UNAVAILABLE.value,
                "framework_id": "Unknown",
                "keyboard_navigation_viable": False,
                "reason": f"UIA error during inspection: {str(e)}"
            }

capability_manager = CapabilityManager()
