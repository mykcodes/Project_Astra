from typing import List, Dict, Any, Optional
from app.interaction.models import InteractionAction, UIObservation, UIElement
from app.interaction.adapters import BaseUIAdapter
from app.interaction.input.engine import input_engine

class StrategyEngine:
    def select_interaction_strategy(self, action: InteractionAction, adapter: BaseUIAdapter, obs: UIObservation, element: Optional[UIElement]) -> List[str]:
        strategies = adapter.get_interaction_strategy()
        applicable = []
        
        if action == InteractionAction.CLICK:
            if "UIA_INVOKE" in strategies and element and "Invoke" in element.supported_patterns:
                applicable.append("UIA_INVOKE")
            if "MOUSE_INJECTION" in strategies:
                applicable.append("MOUSE_INJECTION")
                
        elif action == InteractionAction.TYPE_TEXT:
            if "UIA_VALUE" in strategies and element and "Value" in element.supported_patterns:
                applicable.append("UIA_VALUE")
            applicable.append("KEYBOARD_INJECTION")
            
        elif action == InteractionAction.FOCUS:
            applicable.append("WIN32_FOCUS")
            
        return applicable or ["MOUSE_INJECTION"] # Safe fallback

    def execute_strategy(self, strategy: str, action: InteractionAction, obs: UIObservation, element: Optional[UIElement], value: Optional[str] = None) -> Dict[str, Any]:
        if strategy == "UIA_INVOKE":
            return input_engine.click(element)
        elif strategy == "MOUSE_INJECTION":
            return {"success": False, "reason": "Mouse injection not implemented securely yet"}
        elif strategy == "UIA_VALUE":
            return input_engine.type_text(element, value)
        elif strategy == "KEYBOARD_INJECTION":
            if action == InteractionAction.TYPE_TEXT:
                return input_engine.type_text_fallback(value) # Assuming we add this to input_engine
            return {"success": False, "reason": "Keyboard injection not fully implemented"}
        elif strategy == "WIN32_FOCUS":
            from app.environment.window.manager import window_manager
            success = window_manager.restore_and_focus(obs.window.hwnd)
            return {"success": success, "method": "WIN32_FOCUS"}
            
        return {"success": False, "reason": f"Unknown strategy {strategy}"}

strategy_engine = StrategyEngine()
