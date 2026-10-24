import asyncio
import collections
import contextlib
from datetime import datetime, timezone
import threading
import time
from typing import Deque, Dict, List, Optional, Tuple
import numpy as np

from app.core.logging.logger import get_logger
from app.domain.visual import VisualObservation, VisualCaptureError
from app.domain.observation import (
    MultimodalObservation,
    PerceptualDiffResult,
    BoundingBox,
    CoordinateSpace,
)
from app.environment.visual.capture import ScreenCaptureProvider, screen_capture_provider
from app.environment.visual.diff import PerceptualDiffEngine, perceptual_diff_engine
from app.environment.visual.perception import OcrPerceptionProvider, ocr_perception_provider
from app.environment.window.manager import WindowManager

logger = get_logger(__name__)


class DesktopObserver:
    """
    Lightweight, conservative background observer and observation scheduler.
    
    Responsibilities:
    - Non-intrusive desktop polling (1-2 Hz active, throttling to ~0.67 Hz idle).
    - Perceptual diffing of downscaled frames (<2ms).
    - Zero redundant OCR when desktop state is unchanged.
    - Synchronous forced-refresh path for target verification and pre-actuation.
    - Guaranteed mutual exclusion between background observation and physical actuation.
    - Bounded temporal ring buffer of MultimodalObservation snapshots.
    - Session isolation and deterministic worker lifecycle.
    """

    def __init__(
        self,
        capture_provider: Optional[ScreenCaptureProvider] = None,
        diff_engine: Optional[PerceptualDiffEngine] = None,
        ocr_provider: Optional[OcrPerceptionProvider] = None,
        window_manager: Optional[WindowManager] = None,
        active_interval_s: float = 0.5,
        idle_interval_s: float = 1.5,
        history_capacity: int = 15,
        change_threshold: float = 0.005,
    ):
        self.capture_provider = capture_provider or screen_capture_provider
        self.diff_engine = diff_engine or perceptual_diff_engine
        self.ocr_provider = ocr_provider or ocr_perception_provider
        self.window_manager = window_manager or WindowManager()

        self.active_interval_s = active_interval_s
        self.idle_interval_s = idle_interval_s
        self.history_capacity = history_capacity
        self.change_threshold = change_threshold

        # Observation ring buffer: bounded snapshot history
        self._history: Deque[MultimodalObservation] = collections.deque(maxlen=history_capacity)
        self._history_lock = threading.Lock()

        # Cache of previous frame for diffing
        self._previous_frame: Optional[np.ndarray] = None
        self._last_observation: Optional[MultimodalObservation] = None
        self._consecutive_unchanged: int = 0

        # Concurrency & Mutual Exclusion Controls
        self._running = False
        self._stop_event = threading.Event()
        self._worker_thread: Optional[threading.Thread] = None
        self._pause_lock = threading.Lock()
        self._pause_until: float = 0.0
        self._force_refresh_requested = False

        # Synchronization primitives for physical actuation exclusion
        self._cycle_lock = threading.RLock()
        self._actuation_in_progress = threading.Event()
        self._in_cycle = threading.Event()

        # Diagnostic & Performance Telemetry
        self.total_captures: int = 0
        self.ocr_invocations: int = 0
        self.ocr_suppressed_count: int = 0
        self.total_capture_ms: float = 0.0
        self.total_diff_ms: float = 0.0
        self.total_ocr_ms: float = 0.0

    def start(self) -> None:
        """Starts background observer worker thread."""
        if self._running:
            return

        self._running = True
        self._stop_event.clear()
        self._worker_thread = threading.Thread(
            target=self._worker_loop,
            name="DesktopObserverWorker",
            daemon=True,
        )
        self._worker_thread.start()
        logger.info("DesktopObserver background worker started.")

    def stop(self, timeout_s: float = 2.0) -> None:
        """Deterministically stops observer worker thread."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=timeout_s)
        self._worker_thread = None
        logger.info("DesktopObserver background worker stopped.")

    @contextlib.contextmanager
    def actuation_scope(self, settle_s: float = 0.3, timeout_s: float = 5.0):
        """
        Guarantees complete mutual exclusion between physical actuation and observation cycles.

        Lifecycle:
        1. Signals actuation is imminent (_actuation_in_progress.set()).
        2. Waits for any in-flight capture/OCR cycle to finish (acquires _cycle_lock).
        3. Yields to permit exclusive physical input injection.
        4. In finally block: enforces settle delay, releases lock, and clears actuation flag.
        """
        self._actuation_in_progress.set()
        acquired = self._cycle_lock.acquire(timeout=timeout_s)
        if not acquired:
            self._actuation_in_progress.clear()
            logger.error("DesktopObserver: Failed to acquire actuation lock within timeout. In-flight cycle may be stalled.")
            raise TimeoutError("DesktopObserver actuation synchronization timed out waiting for in-flight cycle.")
        try:
            yield
        finally:
            with self._pause_lock:
                self._pause_until = time.monotonic() + settle_s
            self._cycle_lock.release()
            self._actuation_in_progress.clear()
            logger.debug(f"DesktopObserver actuation completed; settling for {settle_s:.3f}s.")

    def pause_actuation(self, duration_s: float = 0.3, wait_in_flight: bool = True, timeout_s: float = 5.0) -> None:
        """
        Pauses observer polling for duration_s during physical actuation and settle interval.
        If wait_in_flight is True, synchronously waits for any active observation cycle to complete first.
        """
        self._actuation_in_progress.set()
        with self._pause_lock:
            target = time.monotonic() + duration_s
            if target > self._pause_until:
                self._pause_until = target
        if wait_in_flight:
            acquired = self._cycle_lock.acquire(timeout=timeout_s)
            if acquired:
                self._cycle_lock.release()
            else:
                logger.warning("DesktopObserver: pause_actuation timed out waiting for in-flight cycle.")
        self._actuation_in_progress.clear()
        logger.debug(f"DesktopObserver paused for {duration_s:.3f}s during actuation.")

    def request_force_refresh(self) -> None:
        """Flags that the next scheduled cycle must bypass OCR suppression."""
        self._force_refresh_requested = True

    def clear_history(self) -> None:
        """Clears snapshot history to prevent leakage across sessions."""
        with self._history_lock:
            self._history.clear()
            self._last_observation = None
            self._previous_frame = None
            self._consecutive_unchanged = 0
        logger.info("DesktopObserver snapshot history cleared.")

    def get_latest_observation(self) -> Optional[MultimodalObservation]:
        """Returns the most recent multimodal observation snapshot."""
        with self._history_lock:
            return self._last_observation

    def get_observation_by_id(self, observation_id: str) -> Optional[MultimodalObservation]:
        """Finds observation by unique ID in bounded history."""
        with self._history_lock:
            for obs in reversed(self._history):
                if obs.observation_id == observation_id:
                    return obs
        return None

    def get_observation_at_time(
        self,
        target_utc: datetime,
        tolerance_s: float = 2.5,
    ) -> Optional[MultimodalObservation]:
        """
        Finds the observation snapshot closest to target_utc within tolerance_s.
        Used for speech utterance temporal alignment.
        """
        with self._history_lock:
            if not self._history:
                return None

            best_obs: Optional[MultimodalObservation] = None
            best_diff = float("inf")

            for obs in self._history:
                # Ensure UTC comparison
                obs_time = obs.captured_at_utc
                if obs_time.tzinfo is None:
                    obs_time = obs_time.replace(tzinfo=timezone.utc)
                tgt_time = target_utc
                if tgt_time.tzinfo is None:
                    tgt_time = tgt_time.replace(tzinfo=timezone.utc)

                diff = abs((obs_time - tgt_time).total_seconds())
                if diff <= tolerance_s and diff < best_diff:
                    best_diff = diff
                    best_obs = obs

            return best_obs

    def capture_and_fuse_now(self, forced_refresh: bool = True, timeout_s: float = 5.0) -> MultimodalObservation:
        """
        Immediately performs capture, diff, foreground window inspection, and OCR,
        returning a fresh MultimodalObservation under synchronization exclusion.
        """
        acquired = self._cycle_lock.acquire(timeout=timeout_s)
        if not acquired:
            raise TimeoutError("DesktopObserver capture_and_fuse_now timed out waiting for cycle lock.")
        try:
            self._in_cycle.set()
            return self._observe_cycle(forced_refresh=forced_refresh)
        finally:
            self._in_cycle.clear()
            self._cycle_lock.release()

    def _worker_loop(self) -> None:
        """Background observation polling loop with mutual exclusion."""
        while not self._stop_event.is_set():
            # Check actuation pause or in-progress actuation
            now = time.monotonic()
            with self._pause_lock:
                pause_remaining = self._pause_until - now

            if pause_remaining > 0 or self._actuation_in_progress.is_set():
                wait_time = max(0.05, min(pause_remaining, 0.1) if pause_remaining > 0 else 0.05)
                self._stop_event.wait(timeout=wait_time)
                continue

            # Check dynamic sleep interval based on desktop activity
            interval = self.idle_interval_s if self._consecutive_unchanged >= 4 else self.active_interval_s

            forced = self._force_refresh_requested
            self._force_refresh_requested = False

            # Acquire cycle lock with brief timeout so worker yields quickly to actuation
            if not self._cycle_lock.acquire(timeout=0.1):
                continue
            try:
                # Re-verify actuation did not start while waiting for lock
                if self._actuation_in_progress.is_set() or time.monotonic() < self._pause_until:
                    continue
                self._in_cycle.set()
                self._observe_cycle(forced_refresh=forced)
            except Exception as e:
                logger.warning(f"DesktopObserver cycle encountered error: {e}")
            finally:
                self._in_cycle.clear()
                self._cycle_lock.release()

            self._stop_event.wait(timeout=interval)

    def _observe_cycle(self, forced_refresh: bool = False) -> MultimodalObservation:
        """Performs a single observation cycle with diffing and selective OCR."""
        obs_id = f"mmo_{int(time.time() * 1000)}"
        t_start = time.perf_counter()

        # Step 1: Capture virtual screen
        t0 = time.perf_counter()
        visual_obs: VisualObservation = self.capture_provider.capture_virtual_screen(obs_id)
        raw_bytes = self.capture_provider.store.retrieve(visual_obs.image_reference)
        cap_ms = (time.perf_counter() - t0) * 1000.0

        current_frame = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(
            (visual_obs.height, visual_obs.width, 4)
        )

        self.total_captures += 1
        self.total_capture_ms += cap_ms

        # Step 2: Perceptual Differencing
        t1 = time.perf_counter()
        diff_result: PerceptualDiffResult = self.diff_engine.compute_diff(
            current_frame=current_frame,
            previous_frame=self._previous_frame,
            change_threshold=self.change_threshold,
            forced_refresh=forced_refresh,
        )
        diff_ms = (time.perf_counter() - t1) * 1000.0
        self.total_diff_ms += diff_ms

        # Step 3: Foreground Window Awareness & UIA Tree Discovery
        active_window = None
        ui_elements = None
        try:
            active_window = self.window_manager.get_foreground_window()
            if active_window and active_window.hwnd:
                from app.interaction.ui.engine import ui_engine
                ui_elements = ui_engine.discover_ui_tree(active_window.hwnd, max_depth=3)
        except Exception as e:
            logger.debug(f"Could not retrieve active window or UIA elements: {e}")

        # Step 4: Selective OCR Execution (Zero Redundant OCR)
        text_detections = []
        if diff_result.has_changed or forced_refresh:
            self._consecutive_unchanged = 0
            t2 = time.perf_counter()
            try:
                text_detections = self.ocr_provider.extract_all_targets(visual_obs)
                self.ocr_invocations += 1
                ocr_ms = (time.perf_counter() - t2) * 1000.0
                self.total_ocr_ms += ocr_ms
            except Exception as e:
                logger.warning(f"OCR execution in observer cycle failed: {e}")
        else:
            self._consecutive_unchanged += 1
            self.ocr_suppressed_count += 1
            # Carry forward previous detections if available
            if self._last_observation:
                text_detections = self._last_observation.text_detections

        # Store downsampled copy or keep previous frame
        self._previous_frame = current_frame

        # Step 5: Deterministic Multimodal Context Fusion
        from app.ai.context.fusion import context_fusion
        multimodal_obs = context_fusion.fuse_observation(
            visual_obs=visual_obs,
            ocr_targets=text_detections,
            active_window=active_window,
            ui_elements=ui_elements,
            audio_context=None,
            diff_result=diff_result,
        )

        with self._history_lock:
            self._history.append(multimodal_obs)
            self._last_observation = multimodal_obs

        return multimodal_obs


desktop_observer = DesktopObserver()
