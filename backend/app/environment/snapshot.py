from typing import Dict, Any, Optional
from datetime import datetime
from app.environment.application.catalog import catalog
from app.environment.system.manager import system_engine
from app.environment.window.manager import window_manager
from app.environment.process.manager import process_manager
from app.environment.models import SystemEntity, WindowEntity

class EnvironmentSnapshot:
    def __init__(self):
        self._static_state: Optional[SystemEntity] = None
        self._last_static_refresh = 0.0
        
        self._foreground_window: Optional[WindowEntity] = None
        self._last_dynamic_refresh = 0.0
        
    def get_static_system_info(self, force: bool = False) -> SystemEntity:
        now = datetime.now().timestamp()
        if force or not self._static_state or (now - self._last_static_refresh > 3600):
            self._static_state = system_engine.get_system_entity()
            self._last_static_refresh = now
        return self._static_state
        
    def get_foreground_window(self, force: bool = False) -> Optional[WindowEntity]:
        now = datetime.now().timestamp()
        if force or (now - self._last_dynamic_refresh > 5):
            self._foreground_window = window_manager.get_foreground_window()
            self._last_dynamic_refresh = now
        return self._foreground_window
        
    def refresh_applications(self):
        catalog.refresh(force=True)
        
    def invalidate_cache(self):
        self._static_state = None
        self._foreground_window = None

snapshot = EnvironmentSnapshot()
