from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timezone
from app.domain.entities import FreshnessState

@dataclass
class FreshnessPolicy:
    """Consumer-provided policy for what freshness is acceptable."""
    max_age_seconds: float
    name: str = ""

# Predefined standard policies
REALTIME_POLICY = FreshnessPolicy(max_age_seconds=2.0, name="realtime")
INTERACTIVE_POLICY = FreshnessPolicy(max_age_seconds=10.0, name="interactive")
BACKGROUND_POLICY = FreshnessPolicy(max_age_seconds=60.0, name="background")
DIAGNOSTIC_POLICY = FreshnessPolicy(max_age_seconds=300.0, name="diagnostic")

class FreshnessEvaluator:
    @staticmethod
    def evaluate(observation_timestamp: datetime, policy: FreshnessPolicy,
                 now: Optional[datetime] = None) -> FreshnessState:
        """
        Evaluates whether an observation meets the given freshness policy.
        """
        if observation_timestamp.tzinfo is None:
            observation_timestamp = observation_timestamp.replace(tzinfo=timezone.utc)
            
        current_time = now or datetime.now(timezone.utc)
        age = current_time - observation_timestamp
        age_seconds = age.total_seconds()
        
        if age_seconds <= policy.max_age_seconds:
            return FreshnessState.FRESH
        elif age_seconds <= policy.max_age_seconds * 6:
            return FreshnessState.STALE
        else:
            return FreshnessState.INVALID
