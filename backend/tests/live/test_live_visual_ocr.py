"""
B.3.3 — Live Test for Real Visual Perception Provider (OCR)

Uses:
- Real B.2 screen capture (ScreenCaptureProvider via DXcam WinRT)
- Real native Windows Media OCR engine analyzing actual desktop pixels
- Real B.3.1 TargetSelectionService
- Real B.3.1 TargetGroundingService
- Real B.2 VisualCoordinateMapper

Validates:
1. Actual desktop screenshot is captured natively.
2. Real OCR inference is executed against those real pixels.
3. Detected text and bounding boxes are printed in test output.
4. Provider creates valid VisualTarget candidates from real pixels.
5. Successfully grounds a visible detected target into a physical ScreenPoint.
6. Does NOT physically click or actuate any input.
"""

import pytest
from app.domain.entities import ScreenPoint
from app.domain.visual import GroundedTarget, VisualObservation, VisualTarget
from app.environment.visual.capture import screen_capture_provider
from app.environment.visual.grounding import target_grounding_service
from app.environment.visual.perception import (
    OcrPerceptionProvider,
    _run_windows_media_ocr,
)
from app.environment.visual.selection import target_selection_service


def test_live_visual_ocr_real_desktop():
    """
    Live test running real OCR on actual desktop pixels.
    Demonstrates end-to-end perception from real pixels to grounded ScreenPoint.
    """
    # 1. Capture real desktop via existing B.2 provider
    obs = screen_capture_provider.capture_virtual_screen("live_desktop_ocr_test")
    assert isinstance(obs, VisualObservation)
    assert obs.width > 0
    assert obs.height > 0
    assert obs.image_reference.startswith("img_")

    print(f"\n[LIVE TEST] Captured screen: {obs.width}x{obs.height} at offset ({obs.virtual_offset_x}, {obs.virtual_offset_y})")

    # 2. Run real OCR engine on real pixels
    provider = OcrPerceptionProvider(image_store=screen_capture_provider.store)
    raw_bytes = screen_capture_provider.store.retrieve(obs.image_reference)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        all_detections = pool.submit(
            _run_windows_media_ocr,
            raw_bytes,
            obs.width,
            obs.height,
        ).result()

    # The test must not silently pass if no actual OCR inference occurs
    assert len(all_detections) > 0, "Real OCR inference returned 0 detections on desktop."

    print(f"[LIVE TEST] Real OCR detected {len(all_detections)} text elements on screen.")
    print("[LIVE TEST] Sample detections from real screen:")
    for idx, (box, text, score) in enumerate(all_detections[:10]):
        print(f"  [{idx+1}] Text: '{text}' | Conf: {score:.2f} | Box: {box}")

    # 3. Pick a known visible word detected by OCR on screen
    chosen_item = None
    for item in all_detections:
        # Choose a word with letters of reasonable length (e.g. 3+ characters)
        if len(item[1]) >= 3 and item[1].isalpha():
            chosen_item = item
            break

    if chosen_item is None:
        chosen_item = all_detections[0]

    query_text = chosen_item[1]
    print(f"\n[LIVE TEST] Querying perception provider for visible target: '{query_text}'")

    # 4. Run provider.find_targets with semantic query
    candidates = provider.find_targets(obs, query=query_text)
    assert len(candidates) > 0, f"Expected at least one candidate for visible text '{query_text}'"

    for candidate in candidates:
        assert isinstance(candidate, VisualTarget)
        assert candidate.source_observation_id == obs.observation_id
        assert 0 <= candidate.bbox_x < obs.width
        assert 0 <= candidate.bbox_y < obs.height
        assert candidate.bbox_width > 0
        assert candidate.bbox_height > 0
        assert 0.0 <= candidate.confidence <= 1.0

    print(f"[LIVE TEST] Provider returned {len(candidates)} candidates matching '{query_text}'.")
    target_to_ground = candidates[0]
    print(f"[LIVE TEST] Candidate target: id={target_to_ground.target_id}, label='{target_to_ground.label}', bbox=({target_to_ground.bbox_x}, {target_to_ground.bbox_y}, {target_to_ground.bbox_width}, {target_to_ground.bbox_height})")

    # 5. Ground target into physical ScreenPoint
    grounded = target_grounding_service.ground(target_to_ground, obs)
    assert isinstance(grounded, GroundedTarget)
    assert grounded.source_observation_id == obs.observation_id
    assert isinstance(grounded.anchor_point, ScreenPoint)
    assert isinstance(grounded.anchor_point.x, int)
    assert isinstance(grounded.anchor_point.y, int)

    print(f"[LIVE TEST] Grounded target '{target_to_ground.label}' to physical ScreenPoint: ({grounded.anchor_point.x}, {grounded.anchor_point.y})")

    # 6. Verify coordinate transformation invariant
    expected_x = target_to_ground.bbox_x + (target_to_ground.bbox_width // 2) + obs.virtual_offset_x
    expected_y = target_to_ground.bbox_y + (target_to_ground.bbox_height // 2) + obs.virtual_offset_y
    assert grounded.anchor_point.x == expected_x
    assert grounded.anchor_point.y == expected_y

    print(f"[LIVE TEST] Coordinate fidelity verified: anchor matches physical virtual-offset formula.")
    print(f"[LIVE TEST] Verification complete: NO physical actuation was performed.")
