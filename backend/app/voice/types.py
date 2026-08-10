"""
ASTRA Voice Pipeline Types

Defines the stages and data structures for backend voice processing.
"""

from dataclasses import dataclass
from enum import Enum


class VoicePipelineStage(str, Enum):
    """Stages the backend is responsible for."""
    TRANSCRIBE = "transcribe"    # Speech to text (STT)
    SYNTHESIZE = "synthesize"    # Text to speech (TTS)


class AudioFormat(str, Enum):
    """Supported audio formats."""
    WAV = "wav"
    PCM = "pcm"
    OGG = "ogg"
    MP3 = "mp3"
    WEBM = "webm"


@dataclass
class TranscriptionRequest:
    audio_data: bytes
    format: AudioFormat
    language: str | None = None


@dataclass
class TranscriptionResult:
    text: str
    confidence: float
    language: str
    duration_ms: int


@dataclass
class SynthesisRequest:
    text: str
    voice_id: str | None = None
    speed: float = 1.0
    format: AudioFormat = AudioFormat.MP3


@dataclass
class SynthesisResult:
    audio_data: bytes
    format: AudioFormat
    duration_ms: int
