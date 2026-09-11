import pytest
import ctypes
from app.environment.visual.capture import screen_capture_provider, DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
from app.domain.visual import VisualObservation

def test_capture_returns_valid_observation():
    """
    Integration test: the provider returns an observation and the dimensions match.
    """
    obs = screen_capture_provider.capture_virtual_screen("int_test_1")
    
    assert isinstance(obs, VisualObservation)
    assert obs.observation_id == "int_test_1"
    assert obs.image_reference.startswith("img_")
    
    # Verify the image bytes can be retrieved
    raw_bytes = screen_capture_provider.store.retrieve(obs.image_reference)
    
    # BGRA takes 4 bytes per pixel
    expected_bytes = obs.width * obs.height * 4
    assert len(raw_bytes) == expected_bytes
    
    # Check dimensions strictly match virtual screen
    def get_metrics():
        user32 = ctypes.windll.user32
        vcx = user32.GetSystemMetrics(78)
        vcy = user32.GetSystemMetrics(79)
        if vcx == 0:
            vcx = user32.GetSystemMetrics(0)
            vcy = user32.GetSystemMetrics(1)
        return vcx, vcy
        
    # We must retrieve metrics under the same DPI context as the capture
    vcx, vcy = screen_capture_provider._with_dpi_awareness(get_metrics)
    
    assert obs.width == vcx
    assert obs.height == vcy
