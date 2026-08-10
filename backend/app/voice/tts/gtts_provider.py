"""
ASTRA gTTS Text-to-Speech Provider

Uses Google Translate TTS (gTTS) to synthesize speech.
Provides a free, keyless backend alternative for prototypes.
"""

import io
import asyncio
from gtts import gTTS

from app.voice.types import SynthesisRequest, SynthesisResult, AudioFormat
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class GTTSProvider:
    def __init__(self):
        pass

    async def synthesize(self, request: SynthesisRequest) -> SynthesisResult:
        """
        Synthesize text into speech using gTTS.
        """
        try:
            logger.info(f"Synthesizing {len(request.text)} characters of text.")
            
            # gTTS is blocking, so run it in a thread pool
            def _generate():
                tts = gTTS(text=request.text, lang='en', slow=False)
                fp = io.BytesIO()
                tts.write_to_fp(fp)
                return fp.getvalue()

            audio_data = await asyncio.to_thread(_generate)

            return SynthesisResult(
                audio_data=audio_data,
                format=AudioFormat.MP3,
                duration_ms=0
            )
        except Exception as e:
            logger.error(f"TTS Error: {e}")
            raise
