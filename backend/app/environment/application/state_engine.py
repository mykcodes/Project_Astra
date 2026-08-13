from typing import Dict, Any, List
from app.environment.models import ApplicationEntity, ApplicationState
from app.environment.process.manager import process_manager
from app.environment.window.manager import window_manager
from app.environment.application.resolver import resolver

class ApplicationStateEngine:
    def get_state(self, application_name: str) -> Dict[str, Any]:
        resolution = resolver.resolve(application_name)
        
        if resolution["status"] != "RESOLVED":
            return {
                "state": ApplicationState.UNKNOWN.value if resolution["status"] == "AMBIGUOUS" else ApplicationState.NOT_INSTALLED.value,
                "resolution": resolution,
                "pids": [],
                "windows": []
            }
            
        candidate: ApplicationEntity = resolution["candidate"]
        pids = process_manager.get_pids_for_names_and_paths(
            expected_names=candidate.process_names,
            target_path=candidate.executable_path,
            package_family_name=candidate.package_family_name
        )
        
        if not pids:
            return {
                "state": ApplicationState.INSTALLED_NOT_RUNNING.value,
                "resolution": resolution,
                "pids": [],
                "windows": []
            }
            
        windows = window_manager.get_windows_for_pids(pids)
        
        if not windows:
            return {
                "state": ApplicationState.RUNNING_NO_WINDOW.value,
                "resolution": resolution,
                "pids": pids,
                "windows": []
            }
            
        foreground = any(w.foreground for w in windows)
        if foreground:
            state = ApplicationState.RUNNING_FOREGROUND.value
        else:
            visible = any(w.visible and not w.minimized for w in windows)
            if visible:
                state = ApplicationState.RUNNING_BACKGROUND.value
            else:
                state = ApplicationState.RUNNING_MINIMIZED.value
                
        return {
            "state": state,
            "resolution": resolution,
            "pids": pids,
            "windows": [w.__dict__ for w in windows]
        }

state_engine = ApplicationStateEngine()
