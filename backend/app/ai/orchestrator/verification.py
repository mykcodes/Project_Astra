from typing import Dict, Any, List
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class VerificationEngine:
    """Verifies that an action achieved its intended state."""
    
    @staticmethod
    def verify_desktop_action(action: str, target: str, state_after: str, process_ids: List[int]) -> bool:
        """
        Verifies a desktop action based on the expected new state.
        state_after is expected to be from ApplicationState enum (e.g. RUNNING_FOREGROUND).
        """
        if action == "OPEN":
            # If the action was OPEN, it should be running
            return state_after in (
                "RUNNING_FOREGROUND", 
                "RUNNING_BACKGROUND", 
                "RUNNING_MINIMIZED",
                "RUNNING_NO_WINDOW"
            )
        elif action == "CLOSE":
            # If the action was CLOSE, it should not be running
            return state_after in ("NOT_INSTALLED", "INSTALLED_NOT_RUNNING")
        elif action == "FOCUS":
            # If the action was FOCUS, it should be foreground
            return state_after == "RUNNING_FOREGROUND"
        elif action == "MINIMIZE":
            return state_after == "RUNNING_MINIMIZED"
        elif action == "RESTORE":
            return state_after in ("RUNNING_FOREGROUND", "RUNNING_BACKGROUND")
        elif action == "STATUS":
            # STATUS is always true if it executed
            return True
        return False
        
    @staticmethod
    def verify_system_action(requested_fields: List[str], returned_data: Dict[str, Any]) -> bool:
        """Verifies that the requested fields were returned."""
        if not requested_fields:
            return True
            
        # Basic check: do the top-level keys requested exist in the data?
        for field in requested_fields:
            if field not in returned_data:
                logger.warning(f"Verification failed: missing field '{field}' in system info.")
                return False
        return True
