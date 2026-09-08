from app.environment.awareness.provider import SystemAwarenessProvider
from app.environment.awareness.windows import WindowsSystemAwarenessProvider
from app.environment.awareness.errors import ObservationError, ProcessQueryError, WindowQueryError, NativeAPIError, StaleHandleError, SystemAPIUnavailableError
from app.environment.awareness.diff import WorldStateChange, WorldStateChangeType, WorldStateDiff, compute_diff
from app.environment.awareness.freshness import FreshnessPolicy, FreshnessEvaluator, REALTIME_POLICY, INTERACTIVE_POLICY, BACKGROUND_POLICY, DIAGNOSTIC_POLICY

def get_awareness_provider() -> SystemAwarenessProvider:
    """Returns the configured system awareness provider."""
    # For Phase A, Windows is the only supported provider
    return WindowsSystemAwarenessProvider()

__all__ = [
    "SystemAwarenessProvider",
    "WindowsSystemAwarenessProvider",
    "ObservationError",
    "ProcessQueryError",
    "WindowQueryError",
    "NativeAPIError",
    "StaleHandleError",
    "SystemAPIUnavailableError",
    "WorldStateChange",
    "WorldStateChangeType",
    "WorldStateDiff",
    "compute_diff",
    "FreshnessPolicy",
    "FreshnessEvaluator",
    "REALTIME_POLICY",
    "INTERACTIVE_POLICY",
    "BACKGROUND_POLICY",
    "DIAGNOSTIC_POLICY",
    "get_awareness_provider"
]
