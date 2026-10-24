import time
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from httpx import AsyncClient, ASGITransport

from app.domain.observation import AudioUtteranceContext, MultimodalObservation
from app.ai.context.fusion import MultimodalContextFusion
from app.voice.types import TranscriptionResult
from app.main import app
from app.ai.orchestrator.session import ConversationSession
from app.ai.providers.types import AIMessage, MessageRole


@pytest.fixture
def sample_history():
    """Create a 3-element observation history spaced 1 second apart."""
    t0 = datetime.now(timezone.utc) - timedelta(seconds=5.0)
    obs1 = MagicMock(spec=MultimodalObservation)
    obs1.observation_id = "obs_t0"
    obs1.captured_at_utc = t0

    obs2 = MagicMock(spec=MultimodalObservation)
    obs2.observation_id = "obs_t1"
    obs2.captured_at_utc = t0 + timedelta(seconds=1.0)

    obs3 = MagicMock(spec=MultimodalObservation)
    obs3.observation_id = "obs_t2"
    obs3.captured_at_utc = t0 + timedelta(seconds=2.0)

    return [obs1, obs2, obs3], t0


def test_correct_association_with_available_historical_observation(sample_history):
    """Utterance near an observation within tolerance must align correctly."""
    history, t0 = sample_history
    fusion = MultimodalContextFusion()

    # Utterance at t0 + 0.95s -> should match obs2 (t0 + 1.0s)
    utt = AudioUtteranceContext(
        utterance_id="utt_1",
        session_id="session_alpha",
        start_time_utc=t0 + timedelta(seconds=0.95),
        transcript_text="click save",
    )

    aligned = fusion.align_utterance_to_observation(utt, history, max_tolerance_s=0.5)
    assert aligned is not None
    assert aligned.observation_id == "obs_t1"
    assert utt.aligned_observation_id == "obs_t1"


def test_rejection_of_expired_or_unavailable_observations(sample_history):
    """Utterance outside tolerance threshold must not fabricate an alignment."""
    history, t0 = sample_history
    fusion = MultimodalContextFusion()

    # Utterance 10 seconds before t0 -> expired / not in history
    utt_past = AudioUtteranceContext(
        utterance_id="utt_old",
        session_id="session_alpha",
        start_time_utc=t0 - timedelta(seconds=10.0),
        transcript_text="click open",
    )
    assert fusion.align_utterance_to_observation(utt_past, history, max_tolerance_s=0.5) is None
    assert utt_past.aligned_observation_id is None

    # Empty history
    assert fusion.align_utterance_to_observation(utt_past, [], max_tolerance_s=0.5) is None


@pytest.mark.asyncio
async def test_invalid_timestamps_produce_explicit_unresolved_association():
    """Malformed or NaN timestamps must fail safely and not crash or fabricate alignment."""
    with patch("app.api.routes.voice.stt_provider") as mock_stt:
        mock_stt.transcribe = AsyncMock(return_value=TranscriptionResult(text="Test", confidence=0.95, language="en", duration_ms=500))

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send non-numeric client_timestamp_ms
            files = {"audio": ("test.wav", b"RIFF....WAVE", "audio/wav")}
            data = {
                "client_timestamp_ms": "not-a-number",
                "utterance_id": "utt_nan",
                "session_id": "sess_1",
            }
            resp = await client.post("/api/voice/transcribe", files=files, data=data)
            assert resp.status_code == 200
            res_json = resp.json()
            assert res_json["aligned_observation_id"] is None
            assert res_json["clock_reliable"] is False


@pytest.mark.asyncio
async def test_clock_domain_skew_does_not_fabricate_association(sample_history):
    """Excessive clock skew (future or distant past) must be rejected."""
    history, _ = sample_history
    with patch("app.api.routes.voice.stt_provider") as mock_stt, \
         patch("app.api.routes.voice.desktop_observer") as mock_obs:
        mock_stt.transcribe = AsyncMock(return_value=TranscriptionResult(text="Test skew", confidence=0.95, language="en", duration_ms=500))
        mock_obs._history = history

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Timestamp 1 hour in the future
            future_ts = (datetime.now(timezone.utc) + timedelta(hours=1)).timestamp() * 1000.0
            files = {"audio": ("test.wav", b"RIFF....WAVE", "audio/wav")}
            data = {"client_timestamp_ms": str(future_ts)}
            resp = await client.post("/api/voice/transcribe", files=files, data=data)
            assert resp.status_code == 200
            res_json = resp.json()
            assert res_json["aligned_observation_id"] is None
            assert res_json["clock_reliable"] is False


@pytest.mark.asyncio
async def test_delayed_transcription_preserves_original_onset_timing(sample_history):
    """Even if transcription is delayed, the alignment references the onset timestamp."""
    history, t0 = sample_history
    matching_obs = history[1]  # obs_t1 (t0 + 1.0s)
    onset_ms = (t0 + timedelta(seconds=1.05)).timestamp() * 1000.0

    async def slow_transcribe(req):
        # Simulate 0.1s transcription delay
        import asyncio
        await asyncio.sleep(0.05)
        return TranscriptionResult(text="delayed utterance", confidence=0.95, language="en", duration_ms=500)

    with patch("app.api.routes.voice.stt_provider") as mock_stt, \
         patch("app.api.routes.voice.desktop_observer") as mock_obs:
        mock_stt.transcribe = AsyncMock(side_effect=slow_transcribe)
        mock_obs._history = history

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            files = {"audio": ("test.wav", b"RIFF....WAVE", "audio/wav")}
            data = {
                "client_timestamp_ms": str(onset_ms),
                "utterance_id": "utt_delayed",
                "session_id": "sess_delayed",
            }
            resp = await client.post("/api/voice/transcribe", files=files, data=data)
            assert resp.status_code == 200
            res_json = resp.json()
            assert res_json["aligned_observation_id"] == "obs_t1"
            assert res_json["clock_reliable"] is True


from app.ai.providers.types import AIMessage, MessageRole, AIResponse, TokenUsage


def test_session_isolation_and_cross_utterance_leak_prevention():
    """Consecutive turns without aligned_observation_id must reset and not leak context."""
    provider_mock = MagicMock()
    provider_mock.generate = AsyncMock(
        return_value=AIResponse(
            content="Understood.",
            model="mock",
            provider="mock",
            usage=TokenUsage(1, 1, 2),
            finish_reason="stop",
        )
    )
    session = ConversationSession(provider=provider_mock)

    # First turn sets aligned_observation_id
    session.execution_context.aligned_observation_id = "obs_turn_1"
    assert session.execution_context.aligned_observation_id == "obs_turn_1"

    # Second turn has no aligned observation -> must reset to None immediately
    async def run_chat():
        async for _ in session.chat_stream("Turn 2 message", aligned_observation_id=None):
            pass

    import asyncio
    asyncio.run(run_chat())

    assert session.execution_context.aligned_observation_id is None

