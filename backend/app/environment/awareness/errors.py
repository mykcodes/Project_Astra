class ObservationError(Exception):
    """Base class for structured environmental failures during observation."""
    pass

class ProcessQueryError(ObservationError):
    """Raised when process enumeration or querying fails."""
    pass

class WindowQueryError(ObservationError):
    """Raised when window enumeration or querying fails."""
    pass

class NativeAPIError(ObservationError):
    """Raised when a Win32/ctypes or other native API call returns malformed data."""
    pass

class StaleHandleError(ObservationError):
    """Raised when a window handle or PID becomes invalid during observation."""
    pass

class SystemAPIUnavailableError(ObservationError):
    """Raised when a required system API is not available."""
    pass
