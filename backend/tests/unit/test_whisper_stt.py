import pytest
import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from app.voice.types import TranscriptionRequest, AudioFormat
from app.voice.stt.whisper_stt import LocalWhisperSTTProvider

@pytest.fixture
def mock_whisper_model():
    mock_module = MagicMock()
    MockModel = MagicMock()
    mock_module.WhisperModel = MockModel
    
    with patch.dict("sys.modules", {"faster_whisper": mock_module}):
        mock_instance = MockModel.return_value
        # Mock the transcribe method
        mock_segment = MagicMock()
        mock_segment.text = "Hello Astra"
        mock_info = MagicMock()
        mock_info.language = "en"
        
        mock_instance.transcribe.return_value = ([mock_segment], mock_info)
        yield MockModel

@pytest.fixture
def mock_settings():
    with patch("app.voice.stt.whisper_stt.get_settings") as mock_get_settings:
        settings = MagicMock()
        settings.astra_local_stt_model = "base.en"
        settings.astra_local_stt_device = "cpu"
        settings.astra_local_stt_compute_type = "int8"
        mock_get_settings.return_value = settings
        yield mock_get_settings

@pytest.mark.asyncio
async def test_whisper_stt_initialization(mock_settings, mock_whisper_model):
    provider = LocalWhisperSTTProvider()
    
    req = TranscriptionRequest(audio_data=b"dummydata", format=AudioFormat.WEBM)
    result = await provider.transcribe(req)
    
    # Check model was loaded
    mock_whisper_model.assert_called_once_with(
        "base.en",
        device="cpu",
        compute_type="int8"
    )
    
    # Check text returned
    assert result.text == "Hello Astra"
    assert result.language == "en"
    
@pytest.mark.asyncio
async def test_whisper_stt_model_loaded_once(mock_settings, mock_whisper_model):
    provider = LocalWhisperSTTProvider()
    
    req = TranscriptionRequest(audio_data=b"dummydata", format=AudioFormat.WEBM)
    
    # Transcribe twice
    await provider.transcribe(req)
    await provider.transcribe(req)
    
    # Model should still only be initialized once
    mock_whisper_model.assert_called_once()

@pytest.mark.asyncio
async def test_whisper_stt_import_error(mock_settings):
    # Simulate faster_whisper not being installed
    with patch.dict("sys.modules", {"faster_whisper": None}):
        provider = LocalWhisperSTTProvider()
        req = TranscriptionRequest(audio_data=b"dummydata", format=AudioFormat.WEBM)
        
        result = await provider.transcribe(req)
        
        assert "Local STT failed" in result.text
        assert result.confidence == 0.0

@pytest.mark.asyncio
async def test_whisper_stt_transcription_error(mock_settings, mock_whisper_model):
    provider = LocalWhisperSTTProvider()
    
    # Force an error during transcription
    mock_whisper_model.return_value.transcribe.side_effect = Exception("CUDA out of memory")
    
    req = TranscriptionRequest(audio_data=b"dummydata", format=AudioFormat.WEBM)
    result = await provider.transcribe(req)
    
    assert "CUDA out of memory" in result.text
    assert result.confidence == 0.0
