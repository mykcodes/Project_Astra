from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.voice.types import TranscriptionRequest, AudioFormat, SynthesisRequest
from app.voice.stt.gemini_stt import GeminiSTTProvider
from app.voice.stt.openai_stt import OpenAISTTProvider
from app.voice.stt.whisper_stt import LocalWhisperSTTProvider
from app.voice.stt.groq_stt import GroqSTTProvider
from app.voice.tts.gtts_provider import GTTSProvider
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
async def transcribe_audio(audio: UploadFile = File(...)):
    """Transcribes an uploaded audio file using Gemini."""
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
        
        return {"text": result.text}
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
