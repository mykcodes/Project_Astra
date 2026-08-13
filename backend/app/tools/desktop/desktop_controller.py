import asyncio
import sys
import subprocess
from typing import Optional, Dict
from app.core.logging.logger import get_logger
from app.environment.application.state_engine import state_engine
from app.environment.application.resolver import resolver
from app.environment.application.catalog import catalog
from app.environment.models import ApplicationState, ApplicationType, ApplicationEntity
from app.environment.window.manager import window_manager
from app.environment.process.manager import process_manager
from enum import Enum

logger = get_logger(__name__)

class ApplicationIntent(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"
    FOCUS = "FOCUS"
    MINIMIZE = "MINIMIZE"
    RESTORE = "RESTORE"
    STATUS = "STATUS"
    RESTART = "RESTART"

class DesktopController:
    def get_application_status(self, application_name: str, force_refresh: bool = False, blocked_apps: list = None) -> dict:
        if force_refresh:
            catalog.refresh(force=True)
            
        status = state_engine.get_state(application_name)
        
        # Enrich the status object for compatibility with old callers
        resolution = status.get("resolution", {})
        entity = resolution.get("candidate")
        
        return {
            "application": application_name,
            "canonical_name": entity.canonical_name if entity else None,
            "state": status["state"],
            "installed": entity.installed if entity else False,
            "running": status["state"] not in (ApplicationState.UNKNOWN.value, ApplicationState.NOT_INSTALLED.value, ApplicationState.INSTALLED_NOT_RUNNING.value),
            "window_found": status["state"] in (ApplicationState.RUNNING_MINIMIZED.value, ApplicationState.RUNNING_BACKGROUND.value, ApplicationState.RUNNING_FOREGROUND.value),
            "foreground": status["state"] == ApplicationState.RUNNING_FOREGROUND.value,
            "pids": status["pids"],
            "launch_type": entity.application_type.value if entity else None,
            "discovery_source": entity.discovery_source if entity else None,
            "entity": entity,
            "windows": status.get("windows", [])
        }

    async def execute_intent(self, intent: ApplicationIntent, application_name: str, blocked_apps: list = None) -> dict:
        logger.info("APPLICATION_INTENT_RESOLVED", extra={"intent": intent.value, "application": application_name})
        
        if intent == ApplicationIntent.STATUS:
            status = self.get_application_status(application_name, blocked_apps=blocked_apps)
            return {"success": True, **status}
            
        status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        
        if not status.get("installed"):
            logger.info("APPLICATION_RESOLUTION_FAILED", extra={"application": application_name})
            return {
                "success": False,
                "requested_name": application_name,
                "state": status["state"],
                "installed": False,
                "reason": "Application not found or blocked"
            }
            
        if intent == ApplicationIntent.OPEN:
            return await self._handle_open(application_name, status, blocked_apps)
        elif intent == ApplicationIntent.CLOSE:
            return await self._handle_close(application_name, status, blocked_apps)
        elif intent == ApplicationIntent.FOCUS:
            return await self._handle_focus(application_name, status, blocked_apps)
        elif intent == ApplicationIntent.MINIMIZE:
            return await self._handle_minimize(application_name, status, blocked_apps)
        elif intent == ApplicationIntent.RESTORE:
            return await self._handle_restore(application_name, status, blocked_apps)
        elif intent == ApplicationIntent.RESTART:
            close_res = await self._handle_close(application_name, status, blocked_apps)
            if not close_res.get("success"):
                return close_res
            return await self._handle_open(application_name, self.get_application_status(application_name, blocked_apps=blocked_apps), blocked_apps)
            
        return {"success": False, "reason": f"Unknown intent: {intent.value}"}

    async def _handle_open(self, application_name: str, status: dict, blocked_apps: list = None) -> dict:
        logger.info("APPLICATION_ACTION_STARTED", extra={"action": "OPEN", "application": application_name})
        
        entity: ApplicationEntity = status.get("entity")
        
        if status["running"] and status["window_found"]:
            if status["windows"]:
                best_hwnd = status["windows"][0]["hwnd"]
                window_manager.restore_and_focus(best_hwnd)
                
            logger.info("APPLICATION_FOCUS_COMPLETED", extra={"application": application_name})
            new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
            return {
                "success": True,
                "requested_name": application_name,
                "canonical_name": entity.canonical_name,
                "state": new_status["state"],
                "installed": True,
                "running": True,
                "focused": new_status["state"] == ApplicationState.RUNNING_FOREGROUND.value,
                "message": "Application is already running and was focused."
            }

        try:
            self._launch(entity)
            await asyncio.sleep(2.0)
            
            new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
            if new_status["state"] != ApplicationState.INSTALLED_NOT_RUNNING.value:
                logger.info("APPLICATION_ACTION_VERIFICATION", extra={"action": "OPEN", "application": application_name, "verified": True})
                return {
                    "success": True,
                    "requested_name": application_name,
                    "canonical_name": entity.canonical_name,
                    "state": new_status["state"],
                    "installed": True,
                    "running": True,
                    "launch_type": entity.application_type.value,
                    "pids": new_status["pids"]
                }
            else:
                logger.warning("APPLICATION_RECOVERY_STARTED", extra={"application": application_name})
                catalog.invalidate(application_name)
                
                recovery_status = self.get_application_status(application_name, force_refresh=True, blocked_apps=blocked_apps)
                if not recovery_status["installed"]:
                    return {
                        "success": False,
                        "requested_name": application_name,
                        "state": ApplicationState.NOT_INSTALLED.value,
                        "installed": False,
                        "reason": "Recovery failed: Application no longer found."
                    }
                    
                self._launch(recovery_status["entity"])
                await asyncio.sleep(2.0)
                
                final_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
                if final_status["state"] != ApplicationState.INSTALLED_NOT_RUNNING.value:
                    logger.info("APPLICATION_ACTION_VERIFICATION", extra={"action": "OPEN", "application": application_name, "recovered": True})
                    return {
                        "success": True,
                        "requested_name": application_name,
                        "canonical_name": recovery_status["entity"].canonical_name,
                        "state": final_status["state"],
                        "installed": True,
                        "running": True,
                        "launch_type": recovery_status["entity"].application_type.value,
                        "pids": final_status["pids"]
                    }
                else:
                    return {
                        "success": False,
                        "requested_name": application_name,
                        "canonical_name": recovery_status["entity"].canonical_name,
                        "state": final_status["state"],
                        "installed": True,
                        "launch_attempted": True,
                        "launch_verified": False,
                        "reason": "Launcher executed but application process was not detected.",
                        "recovery_attempted": True
                    }
                
        except Exception as e:
            logger.error("APPLICATION_ACTION_FAILED", extra={"action": "OPEN", "application": application_name, "error": str(e)})
            return {
                "success": False,
                "requested_name": application_name,
                "state": status["state"],
                "reason": f"Launch error: {str(e)}"
            }

    async def _handle_close(self, application_name: str, status: dict, blocked_apps: list = None) -> dict:
        if not status["running"]:
            return {
                "success": True,
                "requested_name": application_name,
                "canonical_name": status["entity"].canonical_name,
                "state": ApplicationState.INSTALLED_NOT_RUNNING.value,
                "message": "Application is already closed."
            }
            
        closed_windows = False
        if status["windows"]:
            for w in status["windows"]:
                window_manager.close_window(w["hwnd"])
                closed_windows = True
                
        if not closed_windows and status["pids"]:
            # Hard kill if no windows
            for pid in status["pids"]:
                process_manager.terminate_process_tree(pid)
                
        await asyncio.sleep(2.0)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        if new_status["state"] == ApplicationState.INSTALLED_NOT_RUNNING.value:
            return {
                "success": True,
                "requested_name": application_name,
                "canonical_name": status["entity"].canonical_name,
                "state": new_status["state"],
                "message": "Application was gracefully closed."
            }
        else:
            return {
                "success": False,
                "requested_name": application_name,
                "canonical_name": status["entity"].canonical_name,
                "state": new_status["state"],
                "pids": new_status["pids"],
                "reason": "close_failed",
                "message": "Application is still running after attempted close."
            }

    async def _handle_focus(self, application_name: str, status: dict, blocked_apps: list = None) -> dict:
        if not status["running"]:
            return {"success": False, "reason": "Application is not running."}
            
        if status["windows"]:
            best_hwnd = status["windows"][0]["hwnd"]
            window_manager.restore_and_focus(best_hwnd)
            await asyncio.sleep(0.5)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        return {"success": new_status["state"] == ApplicationState.RUNNING_FOREGROUND.value, "state": new_status["state"]}

    async def _handle_minimize(self, application_name: str, status: dict, blocked_apps: list = None) -> dict:
        if status["windows"]:
            for w in status["windows"]:
                window_manager.minimize_window(w["hwnd"])
            await asyncio.sleep(0.5)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        return {"success": new_status["state"] == ApplicationState.RUNNING_MINIMIZED.value, "state": new_status["state"]}

    async def _handle_restore(self, application_name: str, status: dict, blocked_apps: list = None) -> dict:
        if status["windows"]:
            best_hwnd = status["windows"][0]["hwnd"]
            window_manager.restore_window(best_hwnd)
            await asyncio.sleep(0.5)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        return {"success": True, "state": new_status["state"]}

    def _launch(self, entity: ApplicationEntity):
        if entity.application_type in (ApplicationType.WIN32, ApplicationType.GAME):
            if sys.platform == "win32":
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                subprocess.Popen(
                    [entity.launch_target],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                )
            else:
                subprocess.Popen(
                    [entity.launch_target],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        elif entity.application_type == ApplicationType.UWP:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", entity.launch_target])

desktop_controller = DesktopController()
