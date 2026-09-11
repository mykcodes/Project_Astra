from datetime import datetime
from threading import Lock

class InteractionTracker:
    """
    Tracks the timestamp of the last physical interaction.
    Used for point-in-time freshness invalidation.
    """
    def __init__(self):
        self._last_interaction: datetime = datetime.min
        self._lock = Lock()

    def record_interaction(self):
        with self._lock:
            self._last_interaction = datetime.utcnow()

    def get_last_interaction(self) -> datetime:
        with self._lock:
            return self._last_interaction

interaction_tracker = InteractionTracker()
