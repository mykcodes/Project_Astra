from typing import Dict, Any, List
from app.interaction.adapters.base import BaseUIAdapter
from app.interaction.models import UIWindow, UIAutomationSupport

class ChromiumAdapter(BaseUIAdapter):
    @property
    def framework_id(self) -> str:
        return "Chromium"

    def can_handle(self, window: UIWindow) -> bool:
        return window.framework == "Chrome_WidgetWin_1" or "chrome" in window.application_identity.lower() or "msedge" in window.application_identity.lower()

    def get_accessibility_capabilities(self, hwnd: int) -> Dict[str, Any]:
        return {
            "status": UIAutomationSupport.PARTIAL.value,
            "framework_id": self.framework_id,
            "keyboard_navigation_viable": True,
            "semantic_click_available": False,
            "reason": "Chromium monolithic render surface"
        }

    def get_discovery_strategy(self) -> List[str]:
        return ["UIA", "CHROMIUM_ACCESSIBILITY_PROBE"]

    def get_interaction_strategy(self) -> List[str]:
        return ["KEYBOARD_INJECTION", "UIA_INVOKE", "MOUSE_INJECTION"]
