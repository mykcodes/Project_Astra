import time
import threading
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock
import numpy as np
import pytest

from app.domain.visual import VisualObservation
from app.environment.visual.diff import PerceptualDiffEngine
from app.environment.visual.observer import DesktopObserver


def test_diff_engine_static_frames_suppresses_ocr():
    engine = PerceptualDiffEngine(default_change_threshold=0.005, default_downsample_factor=8, default_noise_tolerance=10)
    
    # 200x200 identical frames
    f1 = np.full((200, 200, 4), 128, dtype=np.uint8)
    f2 = f1.copy()

    # Initial frame
    res1 = engine.compute_diff(f1, None)
    assert res1.has_changed is True
    assert res1.change_ratio == 1.0
    assert res1.ocr_suppressed is False

    # Second identical frame
    res2 = engine.compute_diff(f2, f1)
    assert res2.has_changed is False
    assert res2.change_ratio == 0.0
    assert res2.damage_region is None
    assert res2.ocr_suppressed is True


def test_diff_engine_localized_change_detects_damage_region():
    engine = PerceptualDiffEngine(default_change_threshold=0.002, default_downsample_factor=4, default_noise_tolerance=10)
    
    f1 = np.full((200, 200, 4), 100, dtype=np.uint8)
    f2 = f1.copy()
    
    # Mutate a 40x40 square in the center [80:120, 80:120]
    f2[80:120, 80:120, :3] = 200

    res = engine.compute_diff(f2, f1)
    assert res.has_changed is True
    assert res.change_ratio > 0.0
    assert res.damage_region is not None
    dmg_x, dmg_y, dmg_w, dmg_h = res.damage_region
    # Damage region should cover the mutated region
    assert dmg_x <= 80
    assert dmg_y <= 80
    assert dmg_x + dmg_w >= 120
    assert dmg_y + dmg_h >= 120
    assert res.ocr_suppressed is False


def test_diff_engine_subtle_noise_is_ignored():
    engine = PerceptualDiffEngine(default_change_threshold=0.005, default_noise_tolerance=15)
    
    f1 = np.full((100, 100, 4), 100, dtype=np.uint8)
    f2 = f1.copy()
    # Add subtle noise below tolerance (+5 intensity)
    f2[:, :, :3] += 5

    res = engine.compute_diff(f2, f1)
    assert res.has_changed is False
    assert res.change_ratio == 0.0
    assert res.ocr_suppressed is True


def test_diff_engine_forced_refresh_overrides_identical_frames():
    engine = PerceptualDiffEngine()
    f1 = np.full((100, 100, 4), 50, dtype=np.uint8)
    f2 = f1.copy()

    res = engine.compute_diff(f2, f1, forced_refresh=True)
    assert res.has_changed is True
    assert res.forced_refresh is True
    assert res.ocr_suppressed is False


def test_observer_zero_redundant_ocr_and_forced_refresh():
    mock_capture = MagicMock()
    mock_ocr = MagicMock()
    mock_wm = MagicMock()
    
    # Setup test frames
    f1 = np.full((100, 100, 4), 50, dtype=np.uint8)
    f1_bytes = f1.tobytes()
    mock_capture.store.retrieve.return_value = f1_bytes
    
    obs_meta = VisualObservation(
        observation_id="test_obs",
        captured_at=datetime.now(timezone.utc),
        width=100,
        height=100,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref1",
    )
    mock_capture.capture_virtual_screen.return_value = obs_meta
    mock_ocr.extract_all_targets.return_value = []
    mock_wm.get_foreground_window.return_value = None

    observer = DesktopObserver(
        capture_provider=mock_capture,
        ocr_provider=mock_ocr,
        window_manager=mock_wm,
        history_capacity=5,
    )

    # First cycle: initial frame -> OCR must run
    mmo1 = observer.capture_and_fuse_now(forced_refresh=False)
    assert mock_ocr.extract_all_targets.call_count == 1
    assert observer.ocr_invocations == 1
    assert observer.ocr_suppressed_count == 0
    assert mmo1.diff_from_previous.ocr_suppressed is False

    # Second cycle with identical frame: OCR MUST BE SUPPRESSED (Zero Redundant OCR)
    mmo2 = observer.capture_and_fuse_now(forced_refresh=False)
    assert mock_ocr.extract_all_targets.call_count == 1  # Unchanged!
    assert observer.ocr_suppressed_count == 1
    assert mmo2.diff_from_previous.ocr_suppressed is True

    # Third cycle with forced refresh: OCR must run despite identical frame
    mmo3 = observer.capture_and_fuse_now(forced_refresh=True)
    assert mock_ocr.extract_all_targets.call_count == 2
    assert observer.ocr_invocations == 2
    assert mmo3.diff_from_previous.forced_refresh is True


def test_observer_pause_actuation_and_history():
    mock_capture = MagicMock()
    mock_ocr = MagicMock()
    
    f1 = np.full((50, 50, 4), 10, dtype=np.uint8)
    mock_capture.store.retrieve.return_value = f1.tobytes()
    mock_capture.capture_virtual_screen.return_value = VisualObservation(
        observation_id="obs_hist",
        captured_at=datetime.now(timezone.utc),
        width=50,
        height=50,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref_hist",
    )
    mock_ocr.extract_all_targets.return_value = []

    observer = DesktopObserver(
        capture_provider=mock_capture,
        ocr_provider=mock_ocr,
        history_capacity=3,
    )

    # Test history insertion
    mmo = observer.capture_and_fuse_now()
    assert observer.get_latest_observation() is not None
    assert observer.get_observation_by_id(mmo.observation_id) is not None

    # Test timestamp lookup
    now = datetime.now(timezone.utc)
    found = observer.get_observation_at_time(now, tolerance_s=2.0)
    assert found is not None
    assert found.observation_id == mmo.observation_id

    # Test out of tolerance lookup
    past = now - timedelta(seconds=10)
    assert observer.get_observation_at_time(past, tolerance_s=1.0) is None

    # Test actuation pause
    observer.pause_actuation(duration_s=0.25)
    with observer._pause_lock:
        assert observer._pause_until > time.monotonic()

    # Test clear history
    observer.clear_history()
    assert observer.get_latest_observation() is None
    assert observer.get_observation_by_id(mmo.observation_id) is None


def test_observer_lifecycle_clean_start_stop():
    mock_capture = MagicMock()
    mock_capture.capture_virtual_screen.side_effect = Exception("No capture")

    observer = DesktopObserver(capture_provider=mock_capture)
    observer.start()
    assert observer._running is True
    assert observer._worker_thread is not None
    assert observer._worker_thread.is_alive()

    # Stop observer
    observer.stop(timeout_s=1.0)
    assert observer._running is False
    assert observer._worker_thread is None


def test_observer_actuation_scope_mutual_exclusion():
    """Actuation scope guarantees mutual exclusion with observation cycles."""
    mock_capture = MagicMock()
    f1 = np.full((30, 30, 4), 20, dtype=np.uint8)
    mock_capture.store.retrieve.return_value = f1.tobytes()
    mock_capture.capture_virtual_screen.return_value = VisualObservation(
        observation_id="obs_excl",
        captured_at=datetime.now(timezone.utc),
        width=30,
        height=30,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref_excl",
    )
    mock_ocr = MagicMock()
    mock_ocr.extract_all_targets.return_value = []

    observer = DesktopObserver(
        capture_provider=mock_capture,
        ocr_provider=mock_ocr,
    )

    observation_ran_during_actuation = False
    observation_finished_after_actuation = False

    def try_observe():
        nonlocal observation_ran_during_actuation, observation_finished_after_actuation
        try:
            # Attempt to capture while actuation scope is held with brief timeout
            observer.capture_and_fuse_now(timeout_s=0.1)
            observation_ran_during_actuation = True
        except TimeoutError:
            # Expected to time out while actuation holds cycle lock!
            pass

        # Once actuation is done, should succeed
        try:
            observer.capture_and_fuse_now(timeout_s=1.0)
            observation_finished_after_actuation = True
        except Exception:
            pass

    with observer.actuation_scope(settle_s=0.05):
        assert observer._actuation_in_progress.is_set() is True
        t = threading.Thread(target=try_observe)
        t.start()
        t.join(timeout=0.3)
        assert observation_ran_during_actuation is False

    # Actuation has exited
    assert observer._actuation_in_progress.is_set() is False
    with observer._pause_lock:
        assert observer._pause_until > time.monotonic() - 0.1

    t.join(timeout=1.0)
    assert observation_finished_after_actuation is True


def test_observer_actuation_scope_exception_safety():
    """Exceptions during actuation must release synchronization locks and clear actuation flag."""
    observer = DesktopObserver()

    try:
        with observer.actuation_scope(settle_s=0.2):
            assert observer._actuation_in_progress.is_set() is True
            raise RuntimeError("Actuation hardware error")
    except RuntimeError:
        pass

    # Invariant: lock must be released, actuation flag cleared, settle delay enforced
    assert observer._actuation_in_progress.is_set() is False
    with observer._pause_lock:
        assert observer._pause_until > time.monotonic()
    # Cycle lock must be free to acquire
    acquired = observer._cycle_lock.acquire(timeout=0.2)
    assert acquired is True
    observer._cycle_lock.release()


def test_observer_timestamp_lookup_naive_datetime():
    """Regression test: get_observation_at_time must accept naive datetime without raising TypeError."""
    mock_capture = MagicMock()
    mock_capture.store.retrieve.return_value = bytes(50 * 50 * 4)
    mock_capture.capture_virtual_screen.return_value = VisualObservation(
        observation_id="obs_naive_test",
        captured_at=datetime.now(timezone.utc),
        width=50,
        height=50,
        virtual_offset_x=0,
        virtual_offset_y=0,
        pixel_format="BGRA",
        image_reference="ref_naive",
    )
    mock_ocr = MagicMock()
    mock_ocr.extract_all_targets.return_value = []

    observer = DesktopObserver(
        capture_provider=mock_capture,
        ocr_provider=mock_ocr,
        history_capacity=5,
    )

    mmo = observer.capture_and_fuse_now()

    # Pass a naive datetime (no tzinfo)
    naive_now = datetime.utcnow()
    found = observer.get_observation_at_time(naive_now, tolerance_s=3.0)
    assert found is not None
    assert found.observation_id == mmo.observation_id


def test_observer_deterministic_lifecycle():
    """DesktopObserver worker thread must start and stop deterministically without hanging."""
    observer = DesktopObserver()
    assert observer._running is False
    assert observer._worker_thread is None

    observer.start()
    assert observer._running is True
    assert observer._worker_thread is not None
    assert observer._worker_thread.is_alive()

    # Calling start again must be idempotent
    observer.start()
    assert observer._running is True

    observer.stop(timeout_s=1.0)
    assert observer._running is False
    assert observer._worker_thread is None

    # Calling stop again must be idempotent
    observer.stop(timeout_s=1.0)
    assert observer._running is False


def test_session_prompt_injects_multimodal_observation():
    """Execution session must inject active window and visible elements from desktop_observer into system prompt."""
    from app.ai.orchestrator.session import ConversationSession
    from app.environment.visual.observer import desktop_observer
    from app.domain.observation import MultimodalObservation, MULTIMODAL_SCHEMA_VERSION
    from app.environment.models import WindowEntity
    from app.domain.visual import VisualTarget

    # Create dummy multimodal observation
    win = WindowEntity(
        hwnd=99999,
        title="Test Editor - Document.txt",
        pid=1234,
        process_name="notepad.exe",
        visible=True,
        minimized=False,
        foreground=True,
        fullscreen=False,
        monitor=1,
        x=100,
        y=100,
        width=800,
        height=600,
    )
    target1 = VisualTarget(
        target_id="vt1",
        label="File",
        target_type="menu",
        confidence=0.95,
        bbox_x=10,
        bbox_y=10,
        bbox_width=40,
        bbox_height=20,
        source_observation_id="mmo_prompt_test",
    )
    target2 = VisualTarget(
        target_id="vt2",
        label="Save As",
        target_type="menuitem",
        confidence=0.92,
        bbox_x=10,
        bbox_y=35,
        bbox_width=60,
        bbox_height=20,
        source_observation_id="mmo_prompt_test",
    )

    dummy_mmo = MultimodalObservation(
        observation_id="mmo_prompt_test",
        schema_version=MULTIMODAL_SCHEMA_VERSION,
        captured_at_utc=datetime.now(timezone.utc),
        visual=VisualObservation(
            observation_id="vis_prompt_test",
            captured_at=datetime.now(timezone.utc),
            width=800,
            height=600,
            virtual_offset_x=0,
            virtual_offset_y=0,
            pixel_format="BGRA",
            image_reference="ref_dummy",
        ),
        is_full_virtual_desktop=True,
        capture_region=(0, 0, 800, 600),
        text_detections=[target1, target2],
        active_window=win,
        spatial_hash="testhash12345678",
        modality_availability={"visual": True, "ocr": True, "window": True, "uia": False, "audio": False},
    )

    with desktop_observer._history_lock:
        desktop_observer._last_observation = dummy_mmo
        desktop_observer._history.append(dummy_mmo)

    session = ConversationSession(provider=MagicMock())
    session._update_system_prompt("click save")

    system_prompt = session.history[0].content
    assert "Active Window: Test Editor - Document.txt" in system_prompt
    assert "Visible Elements:" in system_prompt
    assert "'File'" in system_prompt
    assert "'Save As'" in system_prompt

    # Clean up
    desktop_observer.clear_history()


