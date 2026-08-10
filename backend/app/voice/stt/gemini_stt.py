"""
ASTRA Gemini Speech-to-Text Provider

Uses Gemini 1.5/2.0 Flash to transcribe audio files.
"""

import io
from google import genai
from google.genai import types

from app.core.config import get_settings
from app.voice.types import TranscriptionRequest, TranscriptionResult
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class GeminiSTTProvider:
    def __init__(self):
        settings = get_settings()
        if not settings.gemini_api_key:
            logger.warning("Gemini API Key missing. STT will fail.")
            self.client = None
        else:
            self.client = genai.Client(api_key=settings.gemini_api_key)
        # 1.5 flash or 2.0 flash works great for quick transcription
        self.model = "gemini-3.6-flash" 

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        """
        Transcribe audio using Gemini.
        """
        if not self.client:
            raise ValueError("Gemini API Key missing. Cannot transcribe.")
            
        try:
            logger.info("TRANSCRIPTION_STARTED")
            logger.info(f"Transcribing {len(request.audio_data)} bytes of {request.format.value} audio.")
            
            # Map our internal format to MIME type
            mime_type = "audio/wav"
            if request.format.value == "webm":
                mime_type = "audio/webm"
            elif request.format.value == "mp3":
                mime_type = "audio/mp3"
            elif request.format.value == "ogg":
                mime_type = "audio/ogg"
                
            # Create inline data part
            audio_part = types.Part.from_bytes(
                data=request.audio_data,
                mime_type=mime_type
            )
            
            prompt = "Please transcribe this audio accurately. Output ONLY the raw transcript text with no extra formatting, markdown, or conversational filler."
            
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=[audio_part, prompt]
            )
            
            transcript = response.text.strip()
            logger.info("TRANSCRIPTION_COMPLETED")
            
            return TranscriptionResult(
                text=transcript,
                confidence=1.0, # Gemini doesn't return confidence scores
                language="en", 
                duration_ms=0
            )
        except Exception as e:
            logger.error(f"STT Error: {e}")
            raise
