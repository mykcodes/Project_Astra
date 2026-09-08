from abc import ABC, abstractmethod
from typing import List, Optional
from app.domain.entities import WorldState, ApplicationInfo, WindowInfo, ForegroundInfo

class SystemAwarenessProvider(ABC):
    """
    Abstract Protocol for system state observation.
    Provides canonical point-in-time snapshots of the system.
    """
    
    @abstractmethod
    def observe_world_state(self) -> WorldState:
        """Returns a comprehensive canonical snapshot of the entire system."""
        pass
        
    @abstractmethod
    def observe_applications(self) -> List[ApplicationInfo]:
        """Returns observation of all known applications."""
        pass
        
    @abstractmethod
    def observe_application(self, app_name: str) -> ApplicationInfo:
        """Returns observation of a specific application."""
        pass
        
    @abstractmethod
    def observe_windows(self) -> List[WindowInfo]:
        """Returns observation of all open windows."""
        pass
        
    @abstractmethod
    def observe_window(self, hwnd: int) -> WindowInfo:
        """Returns observation of a specific window."""
        pass
        
    @abstractmethod
    def observe_foreground(self) -> Optional[ForegroundInfo]:
        """Returns observation of the current foreground window."""
        pass
