from typing import Dict, Any, Optional, List
from app.environment.snapshot import snapshot
from app.environment.models import WindowEntity

class ContextEngine:
    def __init__(self):
        self.current_intent: Optional[str] = None
        self.current_application: Optional[str] = None
        self.recent_applications: List[str] = []
        self.recent_actions: List[Dict[str, Any]] = []
        self.last_action_result: Optional[Dict[str, Any]] = None
        self.last_referenced_entity: Optional[str] = None
        
    def get_foreground_application(self) -> Optional[str]:
        fw = snapshot.get_foreground_window()
        if fw and fw.title:
            # Basic extraction, relying on title for fallback
            # Could be improved by mapping pid to application
            return fw.title.split('-')[-1].strip()
        return None
        
    def resolve_reference(self, reference: str) -> Optional[str]:
        reference = reference.lower().strip()
        if reference in ("it", "this", "that"):
            return self.current_application or self.last_referenced_entity or self.get_foreground_application()
        return reference
        
    def update_context(self, intent: str, target: Optional[str], result: Optional[Dict[str, Any]] = None):
        self.current_intent = intent
        
        if target and target.lower() not in ("it", "this", "that", "system"):
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
