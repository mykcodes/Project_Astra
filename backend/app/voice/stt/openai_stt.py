import httpx
from app.core.config import get_settings
from app.voice.types import TranscriptionRequest, TranscriptionResult
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class OpenAISTTProvider:
    def __init__(self):
        self.settings = get_settings()
        self.base_url = self.settings.astra_local_base_url.rstrip("/")
        # Using the standard OpenAI Whisper compatible endpoint
        self.endpoint = f"{self.base_url}/audio/transcriptions"

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        logger.info(f"Transcribing {len(request.audio_data)} bytes of {request.format.value} audio using local STT.")
        
        try:
            filename = f"audio.{request.format.value}"
            # map format to MIME type
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
                "model": "whisper-1" # Often ignored by local runtimes, required by API spec
            }

            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(self.endpoint, files=files, data=data)
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
        except httpx.HTTPStatusError as e:
            logger.error(f"Local STT HTTP Error: {e.response.status_code} - {e.response.text}")
            if e.response.status_code == 415:
                # 415 usually means the local server (e.g. LM Studio) does not support audio uploads or STT is not enabled.
                fallback_text = "[System: Local STT failed with 415 Unsupported Media Type. Your local AI server likely does not support audio transcription, or no audio model is loaded.]"
            else:
                fallback_text = f"[System: Local STT failed with status {e.response.status_code}]"
                
            return TranscriptionResult(
                text=fallback_text,
                confidence=0.0,
                language="en",
                duration_ms=0
            )
        except Exception as e:
            logger.error(f"Local STT Error: {e}")
            return TranscriptionResult(
                text=f"[System: Local STT failed: {str(e)}]",
                confidence=0.0,
                language="en",
                duration_ms=0
            )
