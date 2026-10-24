import ctypes
import uuid
import threading
from datetime import datetime
from typing import Dict, Optional, Tuple
import numpy as np

from app.core.logging.logger import get_logger
from app.domain.visual import VisualObservation, VisualCaptureError

logger = get_logger(__name__)

# Windows Constants
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4

class ImageReferenceStore:
    """
    Manages the lifecycle of raw pixel buffers in-memory.
    Ownership of the image buffer belongs strictly to this subsystem.
    """
    def __init__(self, max_capacity: int = 10):
        self._images: Dict[str, bytes] = {}
        self._max_capacity = max_capacity
        self._lock = threading.Lock()

    def store(self, image_data: bytes) -> str:
        """Stores image data and returns an opaque reference."""
        with self._lock:
            if len(self._images) >= self._max_capacity:
                # Evict oldest (insertion order preserved in Python 3.7+)
                oldest_key = next(iter(self._images))
                del self._images[oldest_key]
            
            ref_id = f"img_{uuid.uuid4().hex}"
            self._images[ref_id] = image_data
            return ref_id

    def retrieve(self, ref_id: str) -> bytes:
        """Retrieves image data by reference. Raises error if expired/released."""
        with self._lock:
            if ref_id not in self._images:
                raise VisualCaptureError(
                    "IMAGE_EXPIRED", 
                    f"The image reference {ref_id} is invalid, expired, or has been evicted."
                )
            return self._images[ref_id]

    def release(self, ref_id: str):
        """Explicitly releases an image buffer."""
        with self._lock:
            self._images.pop(ref_id, None)

class DxcamCaptureBackend:
    """
    Adapter for DXcam capturing using the WinRT (Windows.Graphics.Capture) backend.
    """
    def __init__(self):
        try:
            import dxcam
        except ImportError:
            raise VisualCaptureError("CAPTURE_UNAVAILABLE", "dxcam is not installed.")
            
        try:
            self._camera = dxcam.create(backend="winrt", output_color="BGRA")
            if self._camera is None:
                raise VisualCaptureError("CAPTURE_UNAVAILABLE", "dxcam failed to create WinRT camera (returned None).")
        except Exception as e:
            raise VisualCaptureError("CAPTURE_UNAVAILABLE", f"Failed to initialize DXcam WinRT backend: {e}")

    def capture(self) -> np.ndarray:
        try:
            frame = self._camera.grab()
            if frame is None:
                # WinRT may require a few frames to initialize on the first grab
                import time
                for _ in range(10):
                    time.sleep(0.05)
                    frame = self._camera.grab()
                    if frame is not None:
                        break
                        
            if frame is None:
                raise VisualCaptureError("CAPTURE_UNAVAILABLE", "DXcam WinRT returned None (no frame captured).")
                
            if not hasattr(frame, 'shape') or len(frame.shape) != 3 or frame.shape[2] != 4:
                raise VisualCaptureError("CAPTURE_UNAVAILABLE", f"Invalid frame shape or channels: {getattr(frame, 'shape', 'None')}")
                
            if frame.shape[0] == 0 or frame.shape[1] == 0:
                raise VisualCaptureError("CAPTURE_UNAVAILABLE", "Captured frame has zero width or height.")
                
            if frame.dtype != np.uint8:
                raise VisualCaptureError("CAPTURE_UNAVAILABLE", f"Unexpected frame dtype: {frame.dtype}")
                
            return frame
        except VisualCaptureError:
            raise
        except Exception as e:
            raise VisualCaptureError("CAPTURE_UNAVAILABLE", f"Capture exception: {e}")

class ScreenCaptureProvider:
    """
    Provides full virtual-screen capture natively.
    Enforces virtual coordinate invariants to ensure strict physical coordinate mapping.
    """
    def __init__(self):
        self.store = ImageReferenceStore()
        self._backend = DxcamCaptureBackend()

    def _with_dpi_awareness(self, func):
        user32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None)
        if not user32:
            return func()
        
        try:
            original_context = user32.GetThreadDpiAwarenessContext()
        except AttributeError:
            original_context = None

        try:
            if hasattr(user32, "SetThreadDpiAwarenessContext"):
                user32.SetThreadDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception as e:
            logger.warning(f"Failed to set DPI awareness context: {e}")

        try:
            result = func()
        finally:
            if original_context and hasattr(user32, "SetThreadDpiAwarenessContext"):
                user32.SetThreadDpiAwarenessContext(original_context)
                
        return result

    def _get_virtual_screen_bounds(self) -> Tuple[int, int, int, int]:
        """Returns (x, y, width, height) of the physical virtual screen."""
        def _get():
            user32 = ctypes.windll.user32
            x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
            y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
            cx = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
            cy = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
            
            if cx == 0 or cy == 0:
                cx = user32.GetSystemMetrics(0) # SM_CXSCREEN
                cy = user32.GetSystemMetrics(1) # SM_CYSCREEN
                
            return x, y, cx, cy

        return self._with_dpi_awareness(_get)

    def _capture_gdi(self, vx: int, vy: int, vw: int, vh: int) -> Optional[np.ndarray]:
        """Captures arbitrary virtual-screen rectangle using native Win32 GDI BitBlt."""
        user32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None)
        gdi32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "gdi32", None)
        if not user32 or not gdi32:
            return None

        hdc_screen = None
        hdc_mem = None
        hbm = None
        try:
            hdc_screen = user32.GetDC(0)
            if not hdc_screen:
                return None
            hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
            if not hdc_mem:
                return None
            hbm = gdi32.CreateCompatibleBitmap(hdc_screen, vw, vh)
            if not hbm:
                return None
            gdi32.SelectObject(hdc_mem, hbm)
            SRCCOPY = 0x00CC0020
            CAPTUREBLT = 0x40000000
            success = gdi32.BitBlt(hdc_mem, 0, 0, vw, vh, hdc_screen, vx, vy, SRCCOPY | CAPTUREBLT)
            if not success:
                return None

            class BITMAPINFOHEADER(ctypes.Structure):
                _fields_ = [
                    ('biSize', ctypes.c_uint32),
                    ('biWidth', ctypes.c_int32),
                    ('biHeight', ctypes.c_int32),
                    ('biPlanes', ctypes.c_uint16),
                    ('biBitCount', ctypes.c_uint16),
                    ('biCompression', ctypes.c_uint32),
                    ('biSizeImage', ctypes.c_uint32),
                    ('biXPelsPerMeter', ctypes.c_int32),
                    ('biYPelsPerMeter', ctypes.c_int32),
                    ('biClrUsed', ctypes.c_uint32),
                    ('biClrImportant', ctypes.c_uint32),
                ]

            bmi = BITMAPINFOHEADER()
            bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
            bmi.biWidth = vw
            bmi.biHeight = -vh  # top-down row order
            bmi.biPlanes = 1
            bmi.biBitCount = 32
            bmi.biCompression = 0

            buf = (ctypes.c_ubyte * (vw * vh * 4))()
            lines = gdi32.GetDIBits(hdc_mem, hbm, 0, vh, ctypes.byref(buf), ctypes.byref(bmi), 0)
            if lines != vh:
                return None

            return np.frombuffer(buf, dtype=np.uint8).reshape((vh, vw, 4))
        except Exception as e:
            logger.warning(f"GDI BitBlt capture fallback encountered error: {e}")
            return None
        finally:
            if hbm and gdi32:
                gdi32.DeleteObject(hbm)
            if hdc_mem and gdi32:
                gdi32.DeleteDC(hdc_mem)
            if hdc_screen and user32:
                user32.ReleaseDC(0, hdc_screen)

    def capture_virtual_screen(self, observation_id: str) -> VisualObservation:
        """
        Captures the entire virtual screen, proving coordinate invariant before returning.
        Returns a point-in-time VisualObservation metadata object.
        """
        try:
            # 1. Fetch expected physical metrics
            vx, vy, vcx, vcy = self._get_virtual_screen_bounds()
            
            # 2. Capture using primary backend (DXcam)
            frame = None
            try:
                frame = self._backend.capture()
            except Exception as e:
                logger.debug(f"Primary DXcam backend capture failed: {e}. Trying GDI BitBlt fallback...")

            # If DXcam gave mismatched dimensions or failed, attempt GDI BitBlt fallback
            if frame is not None:
                height, width, _ = frame.shape
                if width != vcx or height != vcy:
                    logger.info(
                        f"Primary capture dimensions ({width}x{height}) do not match "
                        f"physical virtual-screen metrics ({vcx}x{vcy}). Attempting GDI BitBlt fallback."
                    )
                    gdi_frame = self._capture_gdi(vx, vy, vcx, vcy)
                    if gdi_frame is not None:
                        frame = gdi_frame
                        height, width, _ = frame.shape
            else:
                gdi_frame = self._capture_gdi(vx, vy, vcx, vcy)
                if gdi_frame is not None:
                    frame = gdi_frame
                    height, width, _ = frame.shape

            if frame is None:
                raise VisualCaptureError(
                    "CAPTURE_UNAVAILABLE",
                    "All capture backends (DXcam and GDI BitBlt) failed to capture screen."
                )

            # 3. Prove invariant: frame dimensions MUST match physical metrics exactly
            if width != vcx or height != vcy:
                raise VisualCaptureError(
                    "DPI_MAPPING_FAILURE",
                    f"Capture dimensions ({width}x{height}) do not match "
                    f"physical virtual-screen metrics ({vcx}x{vcy}). Coordinate fidelity breached."
                )
                
            raw_bytes = frame.tobytes()
            
        except VisualCaptureError:
            raise
        except Exception as e:
            raise VisualCaptureError("CAPTURE_UNAVAILABLE", f"Capture failed: {str(e)}")
        
        # Store raw blob, get opaque reference
        ref_id = self.store.store(raw_bytes)
        
        # Return immutable metadata
        return VisualObservation(
            observation_id=observation_id,
            captured_at=datetime.utcnow(),
            width=vcx,
            height=vcy,
            virtual_offset_x=vx,
            virtual_offset_y=vy,
            pixel_format="BGRA",
            image_reference=ref_id
        )

screen_capture_provider = ScreenCaptureProvider()
