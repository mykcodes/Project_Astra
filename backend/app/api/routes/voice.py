from typing import Optional
from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.voice.types import TranscriptionRequest, AudioFormat, SynthesisRequest
from app.voice.stt.gemini_stt import GeminiSTTProvider
from app.voice.stt.openai_stt import OpenAISTTProvider
from app.voice.stt.whisper_stt import LocalWhisperSTTProvider
from app.voice.stt.groq_stt import GroqSTTProvider
from app.voice.tts.gtts_provider import GTTSProvider
from app.domain.observation import AudioUtteranceContext
from app.environment.visual.observer import desktop_observer
from app.ai.context.fusion import context_fusion
from app.core.logging.logger import get_logger
from app.core.config import get_settings

logger = get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["Voice"])

settings = get_settings()
if settings.astra_stt_provider == "local":
    stt_provider = LocalWhisperSTTProvider()
elif settings.astra_stt_provider == "groq":
    stt_provider = GroqSTTProvider()
else:
    stt_provider = GeminiSTTProvider()
    
tts_provider = GTTSProvider()

class SynthesizeRequestModel(BaseModel):
    text: str

@router.post("/transcribe")
async def transcribe_audio(
    audio: UploadFile = File(...),
    utterance_id: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    client_timestamp_ms: Optional[str] = Form(None),
    client_duration_ms: Optional[str] = Form(None),
    clock_domain: Optional[str] = Form("CLIENT_WALL_CLOCK_UTC_MS"),
):
    """
    Transcribes an uploaded audio file and associates utterance with desktop context
    from the exact time of speech onset using validated clock domain mapping.
    """
    # 1. Capture exact arrival timestamp BEFORE transcription latency begins
    request_received_utc = datetime.now(timezone.utc)

    try:
        audio_bytes = await audio.read()
        
        # Determine format from filename or content type
        fmt = AudioFormat.WAV
        if audio.filename and audio.filename.endswith(".webm"):
            fmt = AudioFormat.WEBM
        elif audio.content_type == "audio/webm":
            fmt = AudioFormat.WEBM
            
        req = TranscriptionRequest(audio_data=audio_bytes, format=fmt)
        result = await stt_provider.transcribe(req)

        # 2. Clock domain mapping & utterance onset calculation
        utt_id = utterance_id or f"utt_{uuid.uuid4().hex[:8]}"
        aligned_obs_id = None
        start_time_utc = None
        clock_reliable = False

        if client_timestamp_ms is not None:
            try:
                ts_float = float(client_timestamp_ms)
                # Check for valid, positive, non-infinite timestamp
                if ts_float > 0 and not (ts_float != ts_float):  # isnan check
                    client_start_candidate = datetime.fromtimestamp(ts_float / 1000.0, tz=timezone.utc)
                    skew_s = (request_received_utc - client_start_candidate).total_seconds()
                    # Sanity check skew: utterance cannot start in future (>5s) or too far in past (>300s)
                    if -5.0 <= skew_s <= 300.0:
                        start_time_utc = client_start_candidate
                        clock_reliable = True
                    else:
                        logger.warning(
                            f"Voice clock skew out of acceptable bounds ({skew_s:.2f}s). Mapping marked uncertain."
                        )
            except Exception as e:
                logger.warning(f"Malformed client_timestamp_ms '{client_timestamp_ms}': {e}")

        # Fallback clock mapping using request arrival and measured audio duration
        if not clock_reliable and client_duration_ms is not None:
            try:
                dur_float = float(client_duration_ms)
                if 0 < dur_float <= 120000:  # Valid audio length <= 2 minutes
                    from datetime import timedelta
                    start_time_utc = request_received_utc - timedelta(milliseconds=dur_float)
                    clock_reliable = True
            except Exception:
                pass

        # 3. Retrieve historical observation snapshot at utterance onset
        if clock_reliable and start_time_utc is not None:
            utterance_ctx = AudioUtteranceContext(
                utterance_id=utt_id,
                session_id=session_id,
                client_timestamp_ms=client_timestamp_ms,
                start_time_utc=start_time_utc,
                transcript_text=result.text,
                clock_domain=clock_domain or "CLIENT_WALL_CLOCK_UTC_MS",
            )
            history_snapshots = list(desktop_observer._history)
            aligned_obs = context_fusion.align_utterance_to_observation(
                utterance_ctx, history_snapshots
            )
            if aligned_obs:
                aligned_obs_id = aligned_obs.observation_id
        else:
            logger.info("Speech-to-observation alignment unresolved: clock mapping uncertain or timestamps unavailable.")

        return {
            "text": result.text,
            "utterance_id": utt_id,
            "aligned_observation_id": aligned_obs_id,
            "clock_reliable": clock_reliable,
        }
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        raise HTTPException(status_code=500, detail="Transcription failed")

@router.post("/synthesize")
async def synthesize_speech(request: SynthesizeRequestModel):
    """Synthesizes text into speech using gTTS."""
    try:
        req = SynthesisRequest(text=request.text)
        result = await tts_provider.synthesize(req)
        
        return Response(content=result.audio_data, media_type="audio/mp3")
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        raise HTTPException(status_code=500, detail="Synthesis failed")
