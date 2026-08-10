import time

_start_time: float = 0.0

def set_start_time() -> None:
    global _start_time
    _start_time = time.time()

def get_uptime() -> float:
    """Get application uptime in seconds."""
    if _start_time == 0.0:
        return 0.0
    return time.time() - _start_time
