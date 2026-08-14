from typing import Dict, Any, List, Optional
from app.interaction.models import UIAutomationSupport, UIWindow
from app.environment.process.manager import process_manager
from app.interaction.adapters import BaseUIAdapter, Win32Adapter, ElectronAdapter, ChromiumAdapter
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

try:
    import uiautomation as auto
    HAS_UIA = True
except ImportError:
    HAS_UIA = False

class CapabilityManager:
    """Detects deterministic UI capabilities and decides fallback strategies using layered evidence."""
    
    def __init__(self):
        self.adapters: List[BaseUIAdapter] = [
            ElectronAdapter(),
            ChromiumAdapter(),
            Win32Adapter()
        ]

    def _determine_framework(self, hwnd: int) -> str:
        if not HAS_UIA:
            return "Unknown"
        try:
            window = auto.WindowControl(searchDepth=1, Handle=hwnd)
            return window.FrameworkId
        except Exception:
            return "Unknown"

    def _get_process_name(self, hwnd: int) -> str:
        # We need pid from hwnd
        if not HAS_UIA: return ""
        try:
            window = auto.WindowControl(searchDepth=1, Handle=hwnd)
            pid = window.ProcessId
            process_entity = process_manager.get_process_details(pid)
            if process_entity:
                return process_entity.name
            return ""
        except Exception:
            return ""

    def inspect_window(self, hwnd: int) -> Dict[str, Any]:
        """Deeply inspects the window using layered evidence."""
        if not HAS_UIA:
            return {
                "status": UIAutomationSupport.UNAVAILABLE.value,
                "framework_id": "Unknown",
                "keyboard_navigation_viable": False,
                "semantic_click_available": False,
                "reason": "uiautomation module not available"
            }
            
        framework = self._determine_framework(hwnd)
        process_name = self._get_process_name(hwnd)
        
        dummy_window = UIWindow(
            hwnd=hwnd, process_id=0, application_identity=process_name,
            framework=framework, title="", role="", bounds=None,
            monitor=0, z_order=0, is_main_window=True, is_modal=False,
            is_popup=False, is_minimized=False, is_maximized=False, is_foreground=False
        )

        selected_adapter = None
        for adapter in self.adapters:
            if adapter.can_handle(dummy_window):
                selected_adapter = adapter
                break

        if not selected_adapter:
            selected_adapter = self.adapters[-1] # Fallback to Win32

        caps = selected_adapter.get_accessibility_capabilities(hwnd)
        
        # Capability probing override (actual evidence beats adapter default)
        try:
            window_ctrl = auto.WindowControl(searchDepth=1, Handle=hwnd)
            if window_ctrl.Exists(0.5):
                children = window_ctrl.GetChildren()
                if not children:
                    caps["status"] = UIAutomationSupport.UNAVAILABLE.value
                    caps["reason"] = "Window exposes no UIA children"
                elif len(children) == 1 and children[0].ControlTypeName in ("DocumentControl", "CustomControl", "PaneControl"):
                    sub_children = children[0].GetChildren()
                    if not sub_children:
                        caps["status"] = UIAutomationSupport.PARTIAL.value
                        caps["reason"] = "Monolithic render surface detected (Accessibility likely disabled)"
                else:
                    caps["status"] = UIAutomationSupport.FULL.value
                    caps["semantic_click_available"] = True
                    caps["reason"] = "UIA tree validated"
        except Exception as e:
            caps["status"] = UIAutomationSupport.UNAVAILABLE.value
            caps["reason"] = f"UIA error: {str(e)}"

        return caps

capability_manager = CapabilityManager()
