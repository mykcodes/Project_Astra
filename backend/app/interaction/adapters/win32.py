from typing import Dict, Any, List
from app.interaction.adapters.base import BaseUIAdapter
from app.interaction.models import UIWindow, UIAutomationSupport

class Win32Adapter(BaseUIAdapter):
    @property
    def framework_id(self) -> str:
        return "Win32"

    def can_handle(self, window: UIWindow) -> bool:
        return window.framework in ("Win32", "") and not window.application_identity.lower().endswith("chrome.exe")

    def get_accessibility_capabilities(self, hwnd: int) -> Dict[str, Any]:
        return {
            "status": UIAutomationSupport.FULL.value,
            "framework_id": self.framework_id,
            "keyboard_navigation_viable": True,
            "semantic_click_available": True,
            "reason": "Win32 typical UIA tree support"
        }

    def get_discovery_strategy(self) -> List[str]:
        return ["UIA", "WINDOW_MESSAGES"]

    def get_interaction_strategy(self) -> List[str]:
        return ["UIA_INVOKE", "WIN32_MESSAGE", "MOUSE_INJECTION"]
