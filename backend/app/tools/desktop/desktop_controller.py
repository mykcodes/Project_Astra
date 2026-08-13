import asyncio
import sys
import subprocess
from typing import Optional, Dict
from app.core.logging.logger import get_logger
from app.tools.application_resolver import resolver
from app.tools.desktop.application_state import ApplicationState, ApplicationStatus, LaunchType, ApplicationIntent
from app.tools.desktop.process_manager import process_manager
from app.tools.desktop.window_manager import window_manager

logger = get_logger(__name__)

class DesktopController:
    def get_application_status(self, application_name: str, force_refresh: bool = False, blocked_apps: list = None) -> ApplicationStatus:
        descriptor = resolver.resolve(application_name, blocked_apps=blocked_apps, force_refresh=force_refresh)
        
        status = ApplicationStatus(descriptor=descriptor)
        
        if not descriptor.installed:
            status.state = ApplicationState.NOT_INSTALLED
            return status
            
        # Check processes
        pids = process_manager.get_pids_for_descriptor(descriptor)
        if not pids:
            status.state = ApplicationState.INSTALLED_NOT_RUNNING
            return status
            
        status.pids = pids
        
        # Check windows
        windows = window_manager.get_windows_for_pids(pids)
        if windows:
            status.windows = windows
            if any(w["is_foreground"] for w in windows):
                status.state = ApplicationState.RUNNING_FOREGROUND
            elif all(w["is_minimized"] for w in windows):
                status.state = ApplicationState.RUNNING_MINIMIZED
            else:
                status.state = ApplicationState.RUNNING_BACKGROUND
        else:
            status.state = ApplicationState.RUNNING_NO_WINDOW
            
        return status

    async def execute_intent(self, intent: ApplicationIntent, application_name: str, blocked_apps: list = None) -> dict:
        logger.info("APPLICATION_INTENT_RESOLVED", extra={"intent": intent.value, "application": application_name})
        
        # STATUS Intent is read-only
        if intent == ApplicationIntent.STATUS:
            status = self.get_application_status(application_name, blocked_apps=blocked_apps)
            return {"success": True, **status.to_dict()}
            
        # For actionable intents, first check state
        status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        
        if not status.descriptor.installed:
            logger.info("APPLICATION_RESOLUTION_FAILED", extra={"application": application_name})
            return {
                "success": False,
                "requested_name": application_name,
                "state": status.state.value,
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

    async def _handle_open(self, application_name: str, status: ApplicationStatus, blocked_apps: list = None) -> dict:
        logger.info("APPLICATION_ACTION_STARTED", extra={"action": "OPEN", "application": application_name})
        
        if status.state in (ApplicationState.RUNNING_FOREGROUND, ApplicationState.RUNNING_BACKGROUND, ApplicationState.RUNNING_MINIMIZED, ApplicationState.RUNNING_NO_WINDOW):
            # Already running, attempt focus
            if status.windows:
                best_hwnd = status.windows[0]["hwnd"]
                window_manager.restore_and_focus(best_hwnd)
                
            logger.info("APPLICATION_FOCUS_COMPLETED", extra={"application": application_name})
            new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
            return {
                "success": True,
                "requested_name": application_name,
                "canonical_name": status.descriptor.canonical_name,
                "state": new_status.state.value,
                "installed": True,
                "running": True,
                "focused": new_status.state == ApplicationState.RUNNING_FOREGROUND,
                "message": "Application is already running and was focused."
            }

        # Not running, let's launch
        try:
            self._launch(status.descriptor)
            
            # Wait for it to spin up
            await asyncio.sleep(2.0)
            
            new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
            if new_status.state != ApplicationState.INSTALLED_NOT_RUNNING:
                logger.info("APPLICATION_ACTION_VERIFICATION", extra={"action": "OPEN", "application": application_name, "verified": True})
                return {
                    "success": True,
                    "requested_name": application_name,
                    "canonical_name": status.descriptor.canonical_name,
                    "state": new_status.state.value,
                    "installed": True,
                    "running": True,
                    "launch_type": status.descriptor.launch_type.value,
                    "pids": new_status.pids
                }
            else:
                # RECOVERY ENGINE
                logger.warning("APPLICATION_RECOVERY_STARTED", extra={"application": application_name})
                resolver.invalidate(application_name)
                
                recovery_status = self.get_application_status(application_name, force_refresh=True, blocked_apps=blocked_apps)
                if not recovery_status.descriptor.installed:
                    return {
                        "success": False,
                        "requested_name": application_name,
                        "state": ApplicationState.NOT_INSTALLED.value,
                        "installed": False,
                        "reason": "Recovery failed: Application no longer found."
                    }
                    
                self._launch(recovery_status.descriptor)
                await asyncio.sleep(2.0)
                
                final_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
                if final_status.state != ApplicationState.INSTALLED_NOT_RUNNING:
                    logger.info("APPLICATION_ACTION_VERIFICATION", extra={"action": "OPEN", "application": application_name, "recovered": True})
                    return {
                        "success": True,
                        "requested_name": application_name,
                        "canonical_name": final_status.descriptor.canonical_name,
                        "state": final_status.state.value,
                        "installed": True,
                        "running": True,
                        "launch_type": final_status.descriptor.launch_type.value,
                        "pids": final_status.pids
                    }
                else:
                    logger.error("APPLICATION_ACTION_FAILED", extra={"action": "OPEN", "application": application_name})
                    return {
                        "success": False,
                        "requested_name": application_name,
                        "canonical_name": final_status.descriptor.canonical_name,
                        "state": final_status.state.value,
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
                "state": status.state.value,
                "reason": f"Launch error: {str(e)}"
            }

    async def _handle_close(self, application_name: str, status: ApplicationStatus, blocked_apps: list = None) -> dict:
        logger.info("APPLICATION_ACTION_STARTED", extra={"action": "CLOSE", "application": application_name})
        
        if status.state in (ApplicationState.UNKNOWN, ApplicationState.NOT_INSTALLED, ApplicationState.INSTALLED_NOT_RUNNING):
            return {
                "success": True,
                "requested_name": application_name,
                "canonical_name": status.descriptor.canonical_name,
                "state": ApplicationState.INSTALLED_NOT_RUNNING.value,
                "message": "Application is already closed."
            }
            
        closed_windows = False
        if status.windows:
            for w in status.windows:
                window_manager.close_window(w["hwnd"])
                closed_windows = True
                
        if closed_windows:
            await asyncio.sleep(2.0)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        if new_status.state == ApplicationState.INSTALLED_NOT_RUNNING:
            logger.info("APPLICATION_ACTION_COMPLETED", extra={"action": "CLOSE", "application": application_name})
            return {
                "success": True,
                "requested_name": application_name,
                "canonical_name": status.descriptor.canonical_name,
                "state": new_status.state.value,
                "message": "Application was gracefully closed."
            }
        else:
            return {
                "success": False,
                "requested_name": application_name,
                "canonical_name": status.descriptor.canonical_name,
                "state": new_status.state.value,
                "pids": new_status.pids,
                "reason": "close_failed",
                "message": "Application is still running after attempted graceful close. It may have minimized to tray or refused the close signal."
            }

    async def _handle_focus(self, application_name: str, status: ApplicationStatus, blocked_apps: list = None) -> dict:
        if status.state in (ApplicationState.INSTALLED_NOT_RUNNING, ApplicationState.NOT_INSTALLED):
            return {"success": False, "reason": "Application is not running."}
            
        if status.windows:
            best_hwnd = status.windows[0]["hwnd"]
            window_manager.restore_and_focus(best_hwnd)
            await asyncio.sleep(0.5)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        return {"success": new_status.state == ApplicationState.RUNNING_FOREGROUND, "state": new_status.state.value}

    async def _handle_minimize(self, application_name: str, status: ApplicationStatus, blocked_apps: list = None) -> dict:
        if status.windows:
            for w in status.windows:
                window_manager.minimize_window(w["hwnd"])
            await asyncio.sleep(0.5)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        return {"success": new_status.state == ApplicationState.RUNNING_MINIMIZED, "state": new_status.state.value}

    async def _handle_restore(self, application_name: str, status: ApplicationStatus, blocked_apps: list = None) -> dict:
        if status.windows:
            best_hwnd = status.windows[0]["hwnd"]
            window_manager.restore_window(best_hwnd)
            await asyncio.sleep(0.5)
            
        new_status = self.get_application_status(application_name, blocked_apps=blocked_apps)
        return {"success": True, "state": new_status.state.value}

    def _launch(self, descriptor):
        if descriptor.launch_type == LaunchType.WIN32:
            if sys.platform == "win32":
                DETACHED_PROCESS = 0x00000008
                CREATE_NEW_PROCESS_GROUP = 0x00000200
                subprocess.Popen(
                    [descriptor.launch_target],
                    creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
                )
            else:
                subprocess.Popen(
                    [descriptor.launch_target],
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
        elif descriptor.launch_type == LaunchType.UWP:
            if sys.platform == "win32":
                subprocess.Popen(["explorer.exe", descriptor.launch_target])

desktop_controller = DesktopController()
