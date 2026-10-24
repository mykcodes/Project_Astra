import hashlib
import time
from typing import Optional, Tuple
import numpy as np

from app.core.logging.logger import get_logger
from app.domain.observation import PerceptualDiffResult

logger = get_logger(__name__)


class PerceptualDiffEngine:
    """
    High-performance, lightweight frame differencing engine for visual perception.
    
    Responsibilities:
    - Downscaled luminance comparison (<2ms per 1080p frame).
    - Thresholded noise rejection to filter GPU dithering, cursor blinks, and micro-antialiasing.
    - Damage region computation for localized UI mutation.
    - Zero redundant OCR signal generation (ocr_suppressed=True when below threshold).
    - Forced-refresh bypass for target verification and safety-critical execution.
    """

    def __init__(
        self,
        default_change_threshold: float = 0.005,  # 0.5% of pixels
        default_downsample_factor: int = 8,       # 1/8th scale (240x135 for 1080p)
        default_noise_tolerance: int = 12,        # Intensity variance [0, 255]
    ):
        self.default_change_threshold = default_change_threshold
        self.default_downsample_factor = default_downsample_factor
        self.default_noise_tolerance = default_noise_tolerance

    def compute_diff(
        self,
        current_frame: np.ndarray,
        previous_frame: Optional[np.ndarray],
        change_threshold: Optional[float] = None,
        downsample_factor: Optional[int] = None,
        noise_tolerance: Optional[int] = None,
        forced_refresh: bool = False,
    ) -> PerceptualDiffResult:
        """
        Compares current_frame against previous_frame.
        
        Args:
            current_frame: Current BGRA or BGR numpy array.
            previous_frame: Preceding frame array, or None if initial.
            change_threshold: Minimum altered pixel ratio to trigger has_changed.
            downsample_factor: Spatial subsampling stride.
            noise_tolerance: Pixel luminance delta to ignore as noise.
            forced_refresh: If True, forces has_changed=True and ocr_suppressed=False.
        """
        t0 = time.perf_counter()
        thresh = change_threshold if change_threshold is not None else self.default_change_threshold
        ds = downsample_factor if downsample_factor is not None else self.default_downsample_factor
        noise = noise_tolerance if noise_tolerance is not None else self.default_noise_tolerance

        if current_frame is None or not hasattr(current_frame, "shape"):
            raise ValueError("current_frame must be a valid numpy array.")

        h, w = current_frame.shape[:2]

        # Initial frame case
        if previous_frame is None:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            digest = hashlib.sha256(current_frame[::ds, ::ds].tobytes()).hexdigest()[:16]
            return PerceptualDiffResult(
                has_changed=True,
                change_ratio=1.0,
                damage_region=(0, 0, w, h),
                diff_hash=digest,
                ocr_suppressed=False,
                forced_refresh=forced_refresh,
                duration_ms=round(elapsed_ms, 2),
            )

        # Dimension mismatch case (resolution changed or window resized)
        if current_frame.shape != previous_frame.shape:
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            digest = hashlib.sha256(current_frame[::ds, ::ds].tobytes()).hexdigest()[:16]
            return PerceptualDiffResult(
                has_changed=True,
                change_ratio=1.0,
                damage_region=(0, 0, w, h),
                diff_hash=digest,
                ocr_suppressed=False,
                forced_refresh=forced_refresh,
                duration_ms=round(elapsed_ms, 2),
            )

        # Subsample frames
        s_curr = current_frame[::ds, ::ds]
        s_prev = previous_frame[::ds, ::ds]

        # Convert to luminance
        if s_curr.ndim == 3 and s_curr.shape[2] >= 3:
            # BGRA/BGR: luminance approx (B + 2*G + R) // 4
            g_curr = (
                s_curr[:, :, 0].astype(np.int16)
                + 2 * s_curr[:, :, 1].astype(np.int16)
                + s_curr[:, :, 2].astype(np.int16)
            ) >> 2
            g_prev = (
                s_prev[:, :, 0].astype(np.int16)
                + 2 * s_prev[:, :, 1].astype(np.int16)
                + s_prev[:, :, 2].astype(np.int16)
            ) >> 2
        else:
            g_curr = s_curr.astype(np.int16)
            g_prev = s_prev.astype(np.int16)

        diff = np.abs(g_curr - g_prev)
        mask = diff > noise
        changed_count = int(np.count_nonzero(mask))
        total_count = mask.size
        change_ratio = changed_count / float(total_count) if total_count > 0 else 0.0

        has_changed = (change_ratio >= thresh) or forced_refresh
        ocr_suppressed = not has_changed and not forced_refresh

        # Compute damage region if changed
        damage_region: Optional[Tuple[int, int, int, int]] = None
        if has_changed and changed_count > 0:
            rows = np.any(mask, axis=1)
            cols = np.any(mask, axis=0)
            if np.any(rows) and np.any(cols):
                rmin, rmax = np.where(rows)[0][[0, -1]]
                cmin, cmax = np.where(cols)[0][[0, -1]]
                dmg_x = int(cmin * ds)
                dmg_y = int(rmin * ds)
                dmg_w = min(w - dmg_x, int((cmax - cmin + 1) * ds))
                dmg_h = min(h - dmg_y, int((rmax - rmin + 1) * ds))
                damage_region = (dmg_x, dmg_y, dmg_w, dmg_h)
            else:
                damage_region = (0, 0, w, h)
        elif forced_refresh:
            damage_region = (0, 0, w, h)

        # Fast perceptual digest of delta mask and downsampled luminance
        digest_bytes = (diff * mask.astype(np.uint8)).tobytes()
        diff_hash = hashlib.sha256(digest_bytes).hexdigest()[:16]

        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        return PerceptualDiffResult(
            has_changed=has_changed,
            change_ratio=round(change_ratio, 4),
            damage_region=damage_region,
            diff_hash=diff_hash,
            ocr_suppressed=ocr_suppressed,
            forced_refresh=forced_refresh,
            duration_ms=round(elapsed_ms, 2),
        )


perceptual_diff_engine = PerceptualDiffEngine()
