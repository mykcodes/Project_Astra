import httpx
from app.core.config import get_settings
from app.voice.types import TranscriptionRequest, TranscriptionResult
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class GroqSTTProvider:
    def __init__(self):
        self.settings = get_settings()
        self.api_key = self.settings.groq_api_key
        self.endpoint = "https://api.groq.com/openai/v1/audio/transcriptions"

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        if not self.api_key:
            raise ValueError("Groq API Key missing. Cannot transcribe.")
            
        logger.info(f"Transcribing {len(request.audio_data)} bytes of {request.format.value} audio using Groq STT.")
        
        try:
            filename = f"audio.{request.format.value}"
            mime_type = "audio/wav"
            if request.format.value == "webm":
                mime_type = "audio/webm"
            elif request.format.value == "mp3":
                mime_type = "audio/mp3"
            elif request.format.value == "ogg":
                mime_type = "audio/ogg"

            files = {
                "file": (filename, request.audio_data, mime_type)
            }
            data = {
                "model": "whisper-large-v3",
                "response_format": "json",
                "language": "en"
            }
            
            headers = {
                "Authorization": f"Bearer {self.api_key}"
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(self.endpoint, files=files, data=data, headers=headers)
                response.raise_for_status()
                result_json = response.json()

            transcript = result_json.get("text", "")
            logger.info("TRANSCRIPTION_COMPLETED")
            
            return TranscriptionResult(
                text=transcript,
                confidence=1.0,
                language="en",
                duration_ms=0
            )
        except Exception as e:
            logger.error(f"Groq STT Error: {e}")
            raise
