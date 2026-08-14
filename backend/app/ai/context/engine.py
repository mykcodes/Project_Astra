from typing import Dict, Any, Optional, List
from app.environment.snapshot import snapshot
from app.interaction.models import UIInteractionContext, UIObservation

class ContextEngine:
    def __init__(self):
        self.current_intent: Optional[str] = None
        self.current_application: Optional[str] = None
        self.recent_applications: List[str] = []
        self.recent_actions: List[Dict[str, Any]] = []
        self.last_action_result: Optional[Dict[str, Any]] = None
        self.last_referenced_entity: Optional[str] = None
        
        self.ui_context = UIInteractionContext()
        
    def get_foreground_application(self) -> Optional[str]:
        fw = snapshot.get_foreground_window()
        if fw and fw.title:
            return fw.title.split('-')[-1].strip()
        return None
        
    def resolve_reference(self, reference: str) -> Optional[str]:
        reference = reference.lower().strip()
        if reference in ("it", "this", "that", "the target"):
            if self.ui_context.current_ui_target:
                return self.ui_context.current_ui_target
            return self.current_application or self.last_referenced_entity or self.get_foreground_application()
        return reference
        
    def update_interaction_context(self, target: str, action: str, success: bool, observation: Optional[UIObservation] = None):
        """Updates interaction-specific short-lived context"""
        self.ui_context.previous_ui_target = self.ui_context.current_ui_target
        self.ui_context.current_ui_target = target
        self.ui_context.interaction_sequence.append(f"{action} on {target}")
        
        if success:
            self.ui_context.last_successful_interaction = action
        else:
            self.ui_context.last_failed_target = target
            
        if observation:
            self.ui_context.last_observed_state = observation
            self.ui_context.foreground_window = observation.foreground_hwnd
            if observation.window:
                self.ui_context.foreground_application = observation.window.application_identity
                if observation.window.is_modal:
                    self.ui_context.active_modal = observation.window.hwnd
                else:
                    self.ui_context.active_modal = None
            
    def invalidate_ui_context(self):
        self.ui_context = UIInteractionContext()
        
    def update_context(self, intent: str, target: Optional[str], result: Optional[Dict[str, Any]] = None):
        self.current_intent = intent
        
        if target and target.lower() not in ("it", "this", "that", "system"):
            if self.current_application != target:
                self.invalidate_ui_context()
                
            self.current_application = target
            self.last_referenced_entity = target
            if target not in self.recent_applications:
                self.recent_applications.insert(0, target)
                if len(self.recent_applications) > 5:
                    self.recent_applications.pop()
                    
        if result:
            self.last_action_result = result
            self.recent_actions.insert(0, result)
            if len(self.recent_actions) > 10:
                self.recent_actions.pop()

context_engine = ContextEngine()
