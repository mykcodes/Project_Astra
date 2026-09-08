import pytest
from datetime import datetime, timezone, timedelta
from app.environment.awareness.freshness import (
    FreshnessPolicy, FreshnessEvaluator, FreshnessState,
    REALTIME_POLICY, DIAGNOSTIC_POLICY
)

def test_freshness_evaluation():
    now = datetime.now(timezone.utc)
    
    # Just observed
    obs_time = now - timedelta(seconds=1)
    
    assert FreshnessEvaluator.evaluate(obs_time, REALTIME_POLICY, now) == FreshnessState.FRESH
    assert FreshnessEvaluator.evaluate(obs_time, DIAGNOSTIC_POLICY, now) == FreshnessState.FRESH
    
    # 5 seconds old (Realtime: STALE, Diagnostic: FRESH)
    obs_time_2 = now - timedelta(seconds=5)
    assert FreshnessEvaluator.evaluate(obs_time_2, REALTIME_POLICY, now) == FreshnessState.STALE
    assert FreshnessEvaluator.evaluate(obs_time_2, DIAGNOSTIC_POLICY, now) == FreshnessState.FRESH
    
    # 20 seconds old (Realtime: INVALID, Diagnostic: FRESH)
    obs_time_3 = now - timedelta(seconds=20)
    assert FreshnessEvaluator.evaluate(obs_time_3, REALTIME_POLICY, now) == FreshnessState.INVALID
    assert FreshnessEvaluator.evaluate(obs_time_3, DIAGNOSTIC_POLICY, now) == FreshnessState.FRESH
