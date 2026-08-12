import os
import tempfile
import time
import asyncio
from app.core.config import get_settings
from app.voice.types import TranscriptionRequest, TranscriptionResult
from app.core.logging.logger import get_logger

logger = get_logger(__name__)

class LocalWhisperSTTProvider:
    def __init__(self):
        self.settings = get_settings()
        self.model = None
        self._lock = asyncio.Lock()
        
    async def _load_model_if_needed(self):
        if self.model is not None:
            return
            
        async with self._lock:
            if self.model is not None:
                return
                
            logger.info("STT_MODEL_LOADING")
            
            try:
                # We import faster_whisper lazily here to not crash the backend on startup 
                # if the user hasn't installed the dependency but isn't using local STT either.
                from faster_whisper import WhisperModel
                
                # Retrieve from settings rather than hardcoding
                model_name = getattr(self.settings, "astra_local_stt_model", "base.en")
                device = getattr(self.settings, "astra_local_stt_device", "cuda")
                compute_type = getattr(self.settings, "astra_local_stt_compute_type", "float16")
                
                self.model = WhisperModel(
                    model_name,
                    device=device,
                    compute_type=compute_type
                )
                logger.info("STT_MODEL_READY")
            except ImportError:
                logger.error("Local STT Error: faster-whisper is not installed. Please pip install faster-whisper.")
                raise
            except Exception as e:
                logger.error(f"Local STT Error: Failed to load Whisper model: {e}")
                raise

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResult:
        logger.info(f"STT_TRANSCRIPTION_STARTED - {len(request.audio_data)} bytes of {request.format.value} audio")
        start_time = time.time()
        
        try:
            await self._load_model_if_needed()
            
            # Write audio bytes to a temporary file
            suffix = f".{request.format.value}"
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(request.audio_data)
                tmp_path = tmp.name

            try:
                # We need to run the CPU-intensive transcribe operation in a thread pool 
                # to not block the asyncio event loop.
                loop = asyncio.get_running_loop()
                segments_generator, info = await loop.run_in_executor(
                    None, 
                    self.model.transcribe, 
                    tmp_path
                )
                
                # Consume the generator to get the text
                def consume_segments():
                    return " ".join([segment.text for segment in segments_generator]).strip()
                    
                text = await loop.run_in_executor(None, consume_segments)
                
            finally:
                # Always clean up the temporary file
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temporary audio file {tmp_path}: {e}")

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info("STT_TRANSCRIPTION_COMPLETED")
            
            return TranscriptionResult(
                text=text,
                confidence=1.0,  # faster-whisper info provides language probability, not overall text confidence easily
                language=info.language if info else "en",
                duration_ms=duration_ms
            )

        except Exception as e:
            logger.error(f"STT_TRANSCRIPTION_FAILED: {e}")
            fallback_text = f"[System: Local STT failed: {str(e)}]"
            return TranscriptionResult(
                text=fallback_text,
                confidence=0.0,
                language="en",
                duration_ms=0
            )
