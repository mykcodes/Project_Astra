from typing import Dict, Any, List
from app.interaction.models import UIWindow, UIObservation, UIAutomationSupport

class BaseUIAdapter:
    """Base interface for all Application/Framework specific interaction adapters."""
    
    @property
    def framework_id(self) -> str:
        return "Unknown"

    def can_handle(self, window: UIWindow) -> bool:
        """Determines if this adapter can handle the given window based on capability layered evidence."""
        return False

    def get_accessibility_capabilities(self, hwnd: int) -> Dict[str, Any]:
        """Deeply inspect the application for capability flags."""
        return {
            "status": UIAutomationSupport.UNKNOWN.value,
            "framework_id": self.framework_id,
            "keyboard_navigation_viable": False,
            "semantic_click_available": False,
            "reason": "Not implemented"
        }

    def get_discovery_strategy(self) -> List[str]:
        """Returns the ordered list of strategies to use for element discovery."""
        return ["UIA"]

    def get_interaction_strategy(self) -> List[str]:
        """Returns the ordered list of strategies for interaction."""
        return ["UIA_INVOKE", "MOUSE_INJECTION"]
