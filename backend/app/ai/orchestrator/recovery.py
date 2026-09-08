from typing import Dict, Any, Optional
from app.core.logging.logger import get_logger
from app.domain.goals import FailureClass
from app.domain.memory import RecoveryStrategy

logger = get_logger(__name__)

class RecoveryEngine:
    """Selects the correct recovery strategy based on the failure class."""
    
    def determine_strategy(self, failure_class: Optional[FailureClass], context: Dict[str, Any] = None) -> RecoveryStrategy:
        if not failure_class:
            return RecoveryStrategy.ABORT_SAFE
            
        strategy = RecoveryStrategy.ABORT_SAFE
        
        if failure_class == FailureClass.TARGET_NOT_FOUND:
            strategy = RecoveryStrategy.REFRESH_OBSERVATION
        elif failure_class == FailureClass.STALE_TARGET:
            strategy = RecoveryStrategy.REFRESH_OBSERVATION
        elif failure_class == FailureClass.PAGE_CHANGED:
            strategy = RecoveryStrategy.REBUILD_TARGET
        elif failure_class == FailureClass.NAVIGATION_TIMEOUT:
            strategy = RecoveryStrategy.INSPECT_NAVIGATION
        elif failure_class == FailureClass.BROWSER_CLOSED:
            strategy = RecoveryStrategy.RECOVER_SESSION
        elif failure_class == FailureClass.CAPTCHA_DETECTED:
            strategy = RecoveryStrategy.WAIT_FOR_USER
        elif failure_class == FailureClass.POPUP_OPENED:
            strategy = RecoveryStrategy.DETERMINE_RELEVANCE
        elif failure_class == FailureClass.CLICK_NO_EFFECT:
            strategy = RecoveryStrategy.ALTERNATE_TARGET
        elif failure_class == FailureClass.VERIFICATION_FAILED:
            strategy = RecoveryStrategy.INSPECT_STATE
        else:
            strategy = RecoveryStrategy.ABORT_SAFE
            
        name = getattr(failure_class, "name", str(failure_class))
        logger.info(f"RecoveryEngine mapped {name} to {strategy.name}")
        return strategy

recovery_engine = RecoveryEngine()
