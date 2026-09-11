from typing import Dict, Any, List, Optional
import urllib.parse
from app.core.logging.logger import get_logger
from app.domain.goals import VerificationResult, FailureClass
from app.tools.desktop.browser.browser_observation import BrowserObservation
from app.domain.entities import TriState

logger = get_logger(__name__)

class VerificationEngine:
    """Verifies that an action achieved its intended state."""
    
    @staticmethod
    def verify_browser_identity(requested_name: str, actual_name: Optional[str]) -> VerificationResult:
        if not actual_name:
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="BROWSER_IDENTITY",
                expected_state=requested_name,
                actual_state="None",
                failure_code=FailureClass.BROWSER_CLOSED,
                evidence="No active browser identity found."
            )
        if requested_name.lower() == actual_name.lower():
            return VerificationResult(
                verified=True,
                verification_type="BROWSER_IDENTITY",
                expected_state=requested_name,
                actual_state=actual_name,
                evidence="Browser identity matches."
            )
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="BROWSER_IDENTITY",
            expected_state=requested_name,
            actual_state=actual_name,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="Browser identity mismatch."
        )
        
    @staticmethod
    def verify_navigation(expected_url: str, obs: BrowserObservation) -> VerificationResult:
        try:
            target_parsed = urllib.parse.urlparse(expected_url if "://" in expected_url else f"http://{expected_url}")
            domain = target_parsed.netloc.replace("www.", "").lower()
            obs_domain = urllib.parse.urlparse(obs.url).netloc.replace("www.", "").lower()
            
            if domain in obs_domain or obs_domain in domain or expected_url.lower() in obs.url.lower():
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="NAVIGATION",
                    expected_state=expected_url,
                    actual_state=obs.url,
                    observation_id=obs.observation_id,
                    evidence="Domain or URL path matches."
                )
        except Exception:
            pass
            
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="NAVIGATION",
            expected_state=expected_url,
            actual_state=obs.url,
            observation_id=obs.observation_id,
            failure_code=FailureClass.PAGE_CHANGED,
            evidence="URL does not match expected navigation target."
        )
        
    @staticmethod
    def verify_search(query: str, obs: BrowserObservation) -> VerificationResult:
        if "search" in obs.url.lower() or "q=" in obs.url.lower():
            return VerificationResult(
                verified=True,
                verification_type="SEARCH",
                expected_state=f"Search for {query}",
                actual_state=obs.url,
                observation_id=obs.observation_id,
                evidence="URL indicates search results."
            )
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="SEARCH",
            expected_state=f"Search for {query}",
            actual_state=obs.url,
            observation_id=obs.observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="URL does not indicate search results."
        )
        
    @staticmethod
    def verify_media_playback(obs_before: BrowserObservation, obs_after: BrowserObservation) -> VerificationResult:
        for m1 in obs_before.media_elements:
            for m2 in obs_after.media_elements:
                if m1.src == m2.src and not m2.paused and m2.current_time > m1.current_time:
                    return VerificationResult(
                        verified=TriState.TRUE,
                        verification_type="MEDIA_PLAYBACK",
                        expected_state="Playing",
                        actual_state=f"Playing at {m2.current_time}s",
                        observation_id=obs_after.observation_id,
                        evidence="Media time progressed and is not paused."
                    )
                    
        for m in obs_after.media_elements:
            if not m.paused and m.current_time > 0:
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="MEDIA_PLAYBACK",
                    expected_state="Playing",
                    actual_state=f"Playing at {m.current_time}s",
                    observation_id=obs_after.observation_id,
                    evidence="Active media element found playing."
                )
                
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="MEDIA_PLAYBACK",
            expected_state="Playing",
            actual_state="Not playing",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="No progressing media playback found."
        )

    @staticmethod
    def verify_click(target: str, obs_before: BrowserObservation, obs_after: BrowserObservation) -> VerificationResult:
        if obs_before.page_signature != obs_after.page_signature:
            return VerificationResult(
                verified=True,
                verification_type="CLICK",
                expected_state="State changed",
                actual_state="State changed",
                observation_id=obs_after.observation_id,
                evidence="Page signature mutated after click."
            )
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="CLICK",
            expected_state="State changed",
            actual_state="State unchanged",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.CLICK_NO_EFFECT,
            evidence="Page signature did not mutate after click."
        )

    @staticmethod
    def verify_interaction(action: str, canonical_identity: str, world_before: 'WorldStateDiff', world_after: 'WorldStateDiff') -> VerificationResult:
        from app.domain.goals import SemanticAction
        
        def is_running(world) -> bool:
            from app.domain.entities import TriState
            if not world or not world.applications:
                return False
            for app in world.applications:
                if app.identity.canonical_name == canonical_identity and app.running == TriState.TRUE:
                    return True
            return False

        if action == SemanticAction.OPEN.value:
            if is_running(world_after):
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="INTERACTION",
                    expected_state="Running",
                    actual_state="Running",
                    evidence=f"Application '{canonical_identity}' found in running state in WorldState."
                )
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="INTERACTION",
                expected_state="Running",
                actual_state="Not running",
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Application '{canonical_identity}' not found running in WorldState."
            )
            
        elif action == SemanticAction.FOCUS.value:
            fg_app = world_after.foreground.owner_application if world_after and world_after.foreground else None
            if fg_app == canonical_identity:
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="INTERACTION",
                    expected_state="Foreground",
                    actual_state="Foreground",
                    evidence=f"Application '{canonical_identity}' is the verified foreground owner."
                )
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="INTERACTION",
                expected_state="Foreground",
                actual_state=f"Foreground: {fg_app}",
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Application '{canonical_identity}' is not the foreground window owner."
            )
            
        elif action == SemanticAction.CLOSE.value:
            if not is_running(world_after):
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="INTERACTION",
                    expected_state="Closed",
                    actual_state="Closed",
                    evidence=f"Application '{canonical_identity}' is not running in WorldState."
                )
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="INTERACTION",
                expected_state="Closed",
                actual_state="Running",
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Application '{canonical_identity}' is still running in WorldState."
            )
            
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="INTERACTION",
            expected_state=action,
            actual_state="Unknown",
            failure_code=FailureClass.UNKNOWN,
            evidence=f"Unknown interaction action: {action}"
        )

    @staticmethod
    def verify_desktop_action(action: str, target: str, state_after: str, process_ids: List[int]) -> bool:
        if action == "OPEN":
            return state_after in ("RUNNING_FOREGROUND", "RUNNING_BACKGROUND", "RUNNING_MINIMIZED", "RUNNING_NO_WINDOW")
        elif action == "CLOSE":
            return state_after in ("NOT_INSTALLED", "INSTALLED_NOT_RUNNING")
        elif action == "FOCUS":
            return state_after == "RUNNING_FOREGROUND"
        elif action == "MINIMIZE":
            return state_after == "RUNNING_MINIMIZED"
        elif action == "RESTORE":
            return state_after in ("RUNNING_FOREGROUND", "RUNNING_BACKGROUND")
        elif action == "STATUS":
            return True
        return False
        
    @staticmethod
    def verify_system_action(requested_fields: List[str], returned_data: Dict[str, Any]) -> bool:
        if not requested_fields:
            return True
        for field in requested_fields:
            if field not in returned_data:
                logger.warning(f"Verification failed: missing field '{field}' in system info.")
                return False
        return True
