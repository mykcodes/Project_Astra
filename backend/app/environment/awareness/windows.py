import time
import platform
import ctypes
from typing import List, Optional
from datetime import datetime, timezone

from app.domain.entities import (
    WorldState, ApplicationInfo, WindowInfo, ForegroundInfo,
    SystemInfo, ApplicationIdentity, WindowBounds, TriState,
    ObservationMetadata, ObservationStatus
)
from app.environment.awareness.provider import SystemAwarenessProvider
from app.environment.awareness.errors import (
    ProcessQueryError, WindowQueryError, NativeAPIError
)
from app.core.logging.logger import get_logger

# Existing managers
from app.environment.window.manager import window_manager
from app.environment.process.manager import process_manager
from app.environment.system.manager import system_engine
from app.environment.application.catalog import catalog

logger = get_logger(__name__)

class WindowsSystemAwarenessProvider(SystemAwarenessProvider):
    
    def _is_zoomed(self, hwnd: int) -> TriState:
        try:
            user32 = ctypes.windll.user32
            # IsZoomed checks if the window is maximized
            result = user32.IsZoomed(hwnd)
            return TriState.TRUE if result != 0 else TriState.FALSE
        except Exception:
            return TriState.UNKNOWN

    def _is_hung(self, hwnd: int) -> TriState:
        try:
            user32 = ctypes.windll.user32
            result = user32.IsHungAppWindow(hwnd)
            return TriState.TRUE if result != 0 else TriState.FALSE
        except Exception:
            return TriState.UNKNOWN

    def _hydrate_process_name(self, w) -> None:
        if w and not w.process_name and w.pid:
            try:
                import psutil
                w.process_name = psutil.Process(w.pid).name()
            except Exception:
                pass
            
    def observe_foreground(self) -> Optional[ForegroundInfo]:
        try:
            fg_win = window_manager.get_foreground_window()
            if not fg_win:
                return None
            self._hydrate_process_name(fg_win)
            return ForegroundInfo(
                handle=fg_win.hwnd,
                owner_application=fg_win.process_name or "",
                title=fg_win.title
            )
        except Exception as e:
            logger.error(f"Failed to observe foreground: {e}")
            return None

    def observe_window(self, hwnd: int) -> WindowInfo:
        try:
            import psutil
            # We fetch all windows for now as window_manager doesn't have get_window_by_hwnd. 
            # In a real implementation we'd optimize this.
            windows = window_manager.get_windows_for_pids(psutil.pids()) 
            for w in windows:
                if w.hwnd == hwnd:
                    self._hydrate_process_name(w)
                    bounds = None
                    if w.width > 0 and w.height > 0:
                        bounds = WindowBounds(x=w.x, y=w.y, width=w.width, height=w.height)
                        
                    is_zoomed = self._is_zoomed(hwnd)
                    is_hung = self._is_hung(hwnd)
                    
                    return WindowInfo(
                        handle=w.hwnd,
                        owner_application=w.process_name or "",
                        owner_pid=w.pid,
                        title=w.title,
                        visible=TriState.TRUE if w.visible else TriState.FALSE,
                        foreground=TriState.TRUE if w.foreground else TriState.FALSE,
                        minimized=TriState.TRUE if w.minimized else TriState.FALSE,
                        maximized=is_zoomed,
                        bounds=bounds,
                        responsive=TriState.FALSE if is_hung == TriState.TRUE else (TriState.TRUE if is_hung == TriState.FALSE else TriState.UNKNOWN)
                    )
            raise WindowQueryError(f"Window {hwnd} not found")
        except Exception as e:
            logger.error(f"Window query failed for {hwnd}: {e}")
            raise WindowQueryError(f"Failed to query window {hwnd}: {e}")

    def observe_windows(self) -> List[WindowInfo]:
        try:
            import psutil
            windows = window_manager.get_windows_for_pids(psutil.pids())
            result = []
            for w in windows:
                self._hydrate_process_name(w)
                bounds = None
                if w.width > 0 and w.height > 0:
                    bounds = WindowBounds(x=w.x, y=w.y, width=w.width, height=w.height)
                    
                is_zoomed = self._is_zoomed(w.hwnd)
                is_hung = self._is_hung(w.hwnd)
                
                result.append(WindowInfo(
                    handle=w.hwnd,
                    owner_application=w.process_name or "",
                    owner_pid=w.pid,
                    title=w.title,
                    visible=TriState.TRUE if w.visible else TriState.FALSE,
                    foreground=TriState.TRUE if w.foreground else TriState.FALSE,
                    minimized=TriState.TRUE if w.minimized else TriState.FALSE,
                    maximized=is_zoomed,
                    bounds=bounds,
                    responsive=TriState.FALSE if is_hung == TriState.TRUE else (TriState.TRUE if is_hung == TriState.FALSE else TriState.UNKNOWN)
                ))
            return result
        except Exception as e:
            logger.error(f"Observe windows failed: {e}")
            raise WindowQueryError(f"Failed to observe windows: {e}")

    def observe_application(self, app_name: str) -> ApplicationInfo:
        try:
            descriptor = catalog.get_all().get(app_name.lower())
            if not descriptor:
                # If not in catalog, treat as UNKNOWN or FALSE? We return FALSE for running if no processes found anyway.
                ident = ApplicationIdentity(
                    canonical_name=app_name.lower(),
                    display_name=app_name,
                    process_names=[app_name]
                )
            else:
                ident = ApplicationIdentity(
                    canonical_name=descriptor.canonical_name,
                    display_name=descriptor.display_name,
                    executable=descriptor.executable_path,
                    process_names=descriptor.process_names,
                    application_type=descriptor.app_type.value if hasattr(descriptor, 'app_type') else "UNKNOWN"
                )

            # Find processes
            target_names = ident.process_names
            pids = process_manager.get_pids_for_names_and_paths(set(target_names))
            
            if not pids:
                return ApplicationInfo(
                    identity=ident,
                    running=TriState.FALSE,
                    process_ids=[],
                    window_count=0,
                    window_handles=[],
                    responsive=TriState.UNKNOWN
                )
                
            # Has processes -> TRUE
            windows = window_manager.get_windows_for_pids(pids)
            handles = [w.hwnd for w in windows]
            
            # Check responsiveness of main windows
            responsive = TriState.UNKNOWN
            if handles:
                responsive = TriState.TRUE
                for hwnd in handles:
                    if self._is_hung(hwnd) == TriState.TRUE:
                        responsive = TriState.FALSE
                        break
                        
            return ApplicationInfo(
                identity=ident,
                running=TriState.TRUE,
                process_ids=pids,
                window_count=len(handles),
                window_handles=handles,
                responsive=responsive
            )
        except Exception as e:
            logger.error(f"Observe application failed for {app_name}: {e}")
            raise ProcessQueryError(f"Failed to observe application {app_name}: {e}")

    def observe_applications(self) -> List[ApplicationInfo]:
        try:
            import psutil
            # We don't want to observe EVERY application in the catalog, only running ones.
            # But the contract might imply all. Let's return running applications based on windows, plus common ones.
            windows = window_manager.get_windows_for_pids(psutil.pids())
            for w in windows:
                self._hydrate_process_name(w)
            
            # Extract unique process names from windows
            process_names = set(w.process_name for w in windows if w.process_name)
            
            apps = []
            for p_name in process_names:
                try:
                    # Simplify by just observing by process name, or resolving via catalog
                    # Since this is a heavy operation, we will construct ApplicationInfo directly for efficiency
                    pids = process_manager.get_pids_for_names_and_paths({p_name})
                    app_windows = [w for w in windows if w.process_name == p_name]
                    handles = [w.hwnd for w in app_windows]
                    
                    responsive = TriState.UNKNOWN
                    if handles:
                        responsive = TriState.TRUE
                        for hwnd in handles:
                            if self._is_hung(hwnd) == TriState.TRUE:
                                responsive = TriState.FALSE
                                break
                    
                    ident = ApplicationIdentity(
                        canonical_name=p_name.lower().replace('.exe', ''),
                        display_name=p_name.replace('.exe', ''),
                        process_names=[p_name]
                    )
                    
                    apps.append(ApplicationInfo(
                        identity=ident,
                        running=TriState.TRUE,
                        process_ids=pids,
                        window_count=len(handles),
                        window_handles=handles,
                        responsive=responsive
                    ))
                except Exception:
                    pass
                    
            return apps
        except Exception as e:
            logger.error(f"Observe applications failed: {e}")
            raise ProcessQueryError(f"Failed to observe applications: {e}")

    def observe_world_state(self) -> WorldState:
        start_time = time.time()
        now = datetime.now(timezone.utc)
        status = ObservationStatus.SUCCESS
        error_msg = None
        
        try:
            # 1. System Info
            os_info = system_engine.get_os_info()
            device_info = system_engine.get_device_info()
            sys_info = SystemInfo(
                os_name=os_info.get("os", "Windows"),
                os_version=os_info.get("os_version", "10"),
                machine_name=device_info.get("device_name", platform.node()),
                timestamp=now.isoformat()
            )
            
            # 2. Windows
            try:
                windows = self.observe_windows()
            except Exception as e:
                windows = []
                status = ObservationStatus.PARTIAL
                error_msg = f"Window observation failed: {e}"
                
            # 3. Applications
            try:
                apps = self.observe_applications()
            except Exception as e:
                apps = []
                status = ObservationStatus.PARTIAL
                error_msg = error_msg + f" | App observation failed: {e}" if error_msg else f"App observation failed: {e}"
                
            # 4. Foreground
            try:
                fg = self.observe_foreground()
            except Exception as e:
                fg = None
                status = ObservationStatus.PARTIAL
                
        except Exception as e:
            logger.error(f"World State observation failed: {e}")
            status = ObservationStatus.FAILED
            error_msg = str(e)
            sys_info = SystemInfo(
                os_name=platform.system(),
                os_version=platform.version(),
                machine_name=platform.node(),
                timestamp=now.isoformat()
            )
            windows = []
            apps = []
            fg = None

        duration_ms = (time.time() - start_time) * 1000
        
        meta = ObservationMetadata(
            timestamp=now,
            source="WindowsSystemAwarenessProvider",
            duration_ms=duration_ms,
            status=status,
            error=error_msg
        )
        
        return WorldState(
            system=sys_info,
            applications=apps,
            windows=windows,
            foreground=fg,
            observation=meta
        )
