from typing import List, Dict, Any, Optional
from enum import Enum
from app.core.logging.logger import get_logger
from app.interaction.ui.engine import ui_engine
from app.environment.window.manager import window_manager
from app.environment.application.state_engine import state_engine

logger = get_logger(__name__)

class RecoveryStrategy(str, Enum):
    UI_TREE_REFRESH = "UI_TREE_REFRESH"
    FOREGROUND_REFRESH = "FOREGROUND_REFRESH"
    TARGET_RE_RESOLUTION = "TARGET_RE_RESOLUTION"
    APPLICATION_STATE_REFRESH = "APPLICATION_STATE_REFRESH"
    ACCESSIBILITY_RELAUNCH = "ACCESSIBILITY_RELAUNCH"

class RecoveryEngine:
    def __init__(self):
        self.max_attempts = 2

    def attempt_recovery(self, attempt: int, failure_category: str, hwnd: int, app_name: str) -> List[RecoveryStrategy]:
        """Determines the appropriate bounded recovery strategy based on failure type."""
        if attempt >= self.max_attempts:
            return []
            
        strategies = []
        
        if failure_category in ("TARGET_NOT_FOUND", "TARGET_AMBIGUOUS", "UI_TREE_EMPTY"):
            ui_engine.invalidate_observation()
            strategies.append(RecoveryStrategy.UI_TREE_REFRESH)
            strategies.append(RecoveryStrategy.TARGET_RE_RESOLUTION)
            
        elif failure_category == "FOCUS_FAILED":
            window_manager.restore_and_focus(hwnd)
            strategies.append(RecoveryStrategy.FOREGROUND_REFRESH)
            
        elif failure_category in ("VERIFICATION_FAILED", "STALE_OBSERVATION"):
            ui_engine.invalidate_observation()
            strategies.append(RecoveryStrategy.UI_TREE_REFRESH)
            
        elif failure_category == "WINDOW_NOT_FOUND":
            state_engine.get_state(app_name) # Force refresh
            strategies.append(RecoveryStrategy.APPLICATION_STATE_REFRESH)
            
        elif failure_category == "UI_AUTOMATION_UNAVAILABLE":
            # We explicitly do NOT auto-relaunch for accessibility unless explicitly configured
            # This is a safe fallback to prevent destroying user data
            pass
            
        return strategies

recovery_engine = RecoveryEngine()
