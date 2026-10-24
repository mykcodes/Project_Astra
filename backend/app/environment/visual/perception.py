"""
B.3.3 — Real Visual Perception Provider (OCR)

Implements the PerceptionProvider protocol using a lightweight, locally executed
OCR engine (Windows.Media.Ocr native WinRT engine / extensible engine interface)
to analyze actual screenshot pixels.

Data Flow:
    VisualObservation (with image_reference)
        → ImageReferenceStore.retrieve()
        → Raw BGRA buffer
        → OCR Engine inference (text + confidence + bounding boxes)
        → Geometry validation (strict observation image space)
        → Semantic query matching (case-insensitive, token/phrase)
        → List[VisualTarget] candidates (source_observation_id preserved)

Zero raw bytes are logged or leaked.
Zero targets are fabricated.
Stale observations and expired references are rejected with structured errors.
"""

import asyncio
import concurrent.futures
import math
import re
from typing import Any, Dict, List, Optional, Protocol, Tuple

import numpy as np

from app.core.logging.logger import get_logger
from app.domain.visual import (
    VisualCaptureError,
    VisualObservation,
    VisualPerceptionError,
    VisualTarget,
)
from app.environment.visual.tracker import interaction_tracker

logger = get_logger(__name__)


class PerceptionProvider(Protocol):
    """
    Abstract contract for visual perception providers (OCR, CV, VLM, etc.).
    Responsibility: "What visual candidates exist?"
    """
    def find_targets(self, observation: VisualObservation, query: str) -> List[VisualTarget]:
        """
        Locate candidate targets matching the query within the observation.
        Must return Image-Space coordinates (bbox_x, bbox_y).
        Must populate intrinsic confidence.
        Must NOT make selection or grounding policy decisions.
        Must NOT fabricate targets if none exist (return empty list).
        """
        ...


def matches_text_query(detected_text: str, query: str) -> bool:
    """
    Deterministic semantic text matching policy.

    Supports:
    - Exact case-insensitive matching
    - Word boundary / token matching (e.g., query "Notepad" in "Untitled - Notepad")
    - Normalized multi-word phrase matching (e.g., query "Open Settings" in "Open Settings App")
    Does NOT falsely match substrings inside longer words (e.g., "Play" does not match "Display").
    """
    q = query.strip().lower()
    t = detected_text.strip().lower()

    if not q or not t:
        return False

    if q == t:
        return True

    # Word boundary regex match
    pattern = r"\b" + re.escape(q) + r"\b"
    if re.search(pattern, t):
        return True

    q_words = re.findall(r"\b\w+\b", q)
    t_words = re.findall(r"\b\w+\b", t)

    # Single-word query: check if it matches an exact token
    if len(q_words) == 1 and q_words[0] in t_words:
        return True

    # Multi-word query: check if normalized phrase matches
    if len(q_words) > 1:
        q_phrase = " ".join(q_words)
        t_phrase = " ".join(t_words)
        if q_phrase in t_phrase:
            return True

    return False


def _run_windows_media_ocr(raw_bytes: bytes, width: int, height: int) -> List[Tuple[Any, str, float]]:
    """
    Runs Windows.Media.Ocr native engine in an MTA worker thread.
    Returns normalized detections: (bbox_or_polygon, text, confidence).
    """
    try:
        import winrt.windows.media.ocr as win_ocr
        import winrt.windows.graphics.imaging as win_imaging
        import winrt.windows.storage.streams as win_streams
    except ImportError as e:
        raise VisualPerceptionError(
            "PERCEPTION_INIT_FAILED",
            f"Windows Media OCR dependencies not available: {e}"
        )

    try:
        engine = win_ocr.OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise VisualPerceptionError(
                "PERCEPTION_INIT_FAILED",
                "Windows OcrEngine.try_create_from_user_profile_languages returned None."
            )

        writer = win_streams.DataWriter()
        writer.write_bytes(raw_bytes)
        buf = writer.detach_buffer()

        sb = win_imaging.SoftwareBitmap(
            win_imaging.BitmapPixelFormat.BGRA8,
            width,
            height,
            win_imaging.BitmapAlphaMode.PREMULTIPLIED
        )
        sb.copy_from_buffer(buf)

        async def _recognize():
            return await engine.recognize_async(sb)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                res = pool.submit(asyncio.run, _recognize()).result()
        else:
            res = asyncio.run(_recognize())
    except VisualPerceptionError:
        raise
    except Exception as e:
        raise VisualPerceptionError(
            "PERCEPTION_INFERENCE_FAILED",
            f"Windows Media OCR recognition failed: {e}"
        )

    detections: List[Tuple[Any, str, float]] = []

    for line in res.lines:
        line_text = line.text.strip()
        if not line_text:
            continue

        # Add word-level detections for precise anchor points
        for w in line.words:
            w_text = w.text.strip()
            if w_text:
                r = w.bounding_rect
                detections.append(([r.x, r.y, r.width, r.height], w_text, 0.99))

        # Add line-level detection for multi-word queries
        if len(line.words) > 1:
            lx = min(w.bounding_rect.x for w in line.words)
            ly = min(w.bounding_rect.y for w in line.words)
            lw = max(w.bounding_rect.x + w.bounding_rect.width for w in line.words) - lx
            lh = max(w.bounding_rect.y + w.bounding_rect.height for w in line.words) - ly
            detections.append(([lx, ly, lw, lh], line_text, 0.99))

    return detections


class OcrPerceptionProvider:
    """
    Production-ready OCR perception provider.
    
    Consumes actual captured image buffers from the ImageReferenceStore associated
    with a VisualObservation and yields validated VisualTarget candidates.
    
    By default, executes local Windows.Media.Ocr native WinRT engine without external weights.
    Supports dependency-injected test doubles for deterministic unit testing.
    """

    def __init__(
        self,
        ocr_engine: Optional[Any] = None,
        image_store: Optional[Any] = None,
    ):
        self._ocr_engine = ocr_engine
        self._image_store = image_store

    @property
    def image_store(self) -> Any:
        if self._image_store is None:
            from app.environment.visual.capture import screen_capture_provider
            self._image_store = screen_capture_provider.store
        return self._image_store

    def find_targets(self, observation: VisualObservation, query: str) -> List[VisualTarget]:
        """
        Runs local OCR on the pixels of observation and returns VisualTarget candidates
        matching query.
        """
        if not query or not query.strip():
            return []

        all_targets = self.extract_all_targets(observation)
        matched = [
            t.model_copy(update={"semantic_attributes": {**t.semantic_attributes, "query": query}})
            for t in all_targets
            if matches_text_query(t.label, query)
        ]
        logger.info("OCR_PERCEPTION_COMPLETED", extra={
            "observation_id": observation.observation_id,
            "query": query,
            "candidates_found": len(matched),
        })
        return matched

    def extract_all_targets(self, observation: VisualObservation) -> List[VisualTarget]:
        """
        Runs OCR and extracts all valid visual text candidates across the observation
        without filtering by a semantic query.
        """
        # 1. Freshness check: Reject observation if physical interaction occurred after capture
        last_interaction = interaction_tracker.get_last_interaction()
        obs_time = observation.captured_at
        if getattr(last_interaction, "tzinfo", None) is not None and getattr(obs_time, "tzinfo", None) is None:
            from datetime import timezone
            obs_time = obs_time.replace(tzinfo=timezone.utc)
        elif getattr(last_interaction, "tzinfo", None) is None and getattr(obs_time, "tzinfo", None) is not None:
            from datetime import timezone
            last_interaction = last_interaction.replace(tzinfo=timezone.utc)

        if last_interaction > obs_time:
            raise VisualCaptureError(
                "STALE_OBSERVATION",
                f"Observation {observation.observation_id} is stale. "
                f"A physical interaction occurred at {last_interaction.isoformat()} "
                f"which is after the capture timestamp {obs_time.isoformat()}."
            )

        # 2. Retrieve image buffer from ImageReferenceStore
        try:
            raw_bytes = self.image_store.retrieve(observation.image_reference)
        except VisualCaptureError:
            raise
        except Exception as e:
            raise VisualPerceptionError(
                "IMAGE_RETRIEVAL_FAILED",
                f"Failed to retrieve image reference {observation.image_reference}: {e}"
            )

        # 3. Verify buffer length and format
        expected_len = observation.width * observation.height * 4
        if len(raw_bytes) != expected_len:
            raise VisualPerceptionError(
                "INVALID_IMAGE_DATA",
                f"Image buffer size mismatch: expected {expected_len} bytes for "
                f"{observation.width}x{observation.height} BGRA, got {len(raw_bytes)} bytes."
            )

        # 4. Run OCR engine
        if self._ocr_engine is not None:
            bgra = np.frombuffer(raw_bytes, dtype=np.uint8).reshape(
                (observation.height, observation.width, 4)
            )
            bgr = bgra[:, :, :3]
            try:
                engine_output = self._ocr_engine(bgr)
                if isinstance(engine_output, tuple):
                    results = engine_output[0]
                else:
                    results = engine_output
            except VisualPerceptionError:
                raise
            except Exception as e:
                raise VisualPerceptionError(
                    "PERCEPTION_INFERENCE_FAILED",
                    f"OCR inference failed: {e}"
                )
        else:
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    results = pool.submit(
                        _run_windows_media_ocr,
                        raw_bytes,
                        observation.width,
                        observation.height,
                    ).result()
            except VisualPerceptionError:
                raise
            except Exception as e:
                raise VisualPerceptionError(
                    "PERCEPTION_INFERENCE_FAILED",
                    f"OCR execution failed: {e}"
                )

        if not results:
            return []

        candidates: List[VisualTarget] = []
        for idx, item in enumerate(results):
            box_or_polygon, detected_text, score = item[0], item[1], item[2]

            if not isinstance(detected_text, str) or not detected_text.strip():
                continue

            if len(box_or_polygon) == 4 and isinstance(box_or_polygon[0], (list, tuple)):
                xs = [float(p[0]) for p in box_or_polygon]
                ys = [float(p[1]) for p in box_or_polygon]
            elif len(box_or_polygon) == 4 and isinstance(box_or_polygon[0], (int, float)):
                x_val = float(box_or_polygon[0])
                y_val = float(box_or_polygon[1])
                w_val = float(box_or_polygon[2])
                h_val = float(box_or_polygon[3])
                xs = [x_val, x_val + w_val]
                ys = [y_val, y_val + h_val]
            else:
                raise VisualPerceptionError(
                    "INVALID_TARGET_GEOMETRY",
                    f"Unexpected bounding box format: {box_or_polygon}"
                )

            if any(math.isnan(x) or math.isinf(x) for x in xs) or any(
                math.isnan(y) or math.isinf(y) for y in ys
            ):
                raise VisualPerceptionError(
                    "INVALID_TARGET_GEOMETRY",
                    "Detection contains non-finite coordinates (NaN or Inf)."
                )

            min_x = int(math.floor(min(xs)))
            max_x = int(math.ceil(max(xs)))
            min_y = int(math.floor(min(ys)))
            max_y = int(math.ceil(max(ys)))
            bbox_width = max_x - min_x
            bbox_height = max_y - min_y

            if min_x < 0 or min_y < 0 or bbox_width <= 0 or bbox_height <= 0:
                raise VisualPerceptionError(
                    "INVALID_TARGET_GEOMETRY",
                    f"Malformed bounding box geometry: ({min_x}, {min_y}, {bbox_width}, {bbox_height})."
                )

            if min_x + bbox_width > observation.width or min_y + bbox_height > observation.height:
                raise VisualPerceptionError(
                    "INVALID_TARGET_GEOMETRY",
                    f"Detection bounding box ({min_x}, {min_y}, {bbox_width}, {bbox_height}) "
                    f"exceeds observation dimensions ({observation.width}x{observation.height})."
                )

            confidence = float(score)
            if math.isnan(confidence) or math.isinf(confidence) or confidence < 0.0 or confidence > 1.0:
                raise VisualPerceptionError(
                    "INVALID_TARGET_CONFIDENCE",
                    f"Detection confidence {confidence} is outside valid range [0.0, 1.0]."
                )

            target_id = f"ocr_target_{observation.observation_id}_{idx}"
            candidates.append(
                VisualTarget(
                    target_id=target_id,
                    label=detected_text,
                    target_type="text",
                    confidence=confidence,
                    bbox_x=min_x,
                    bbox_y=min_y,
                    bbox_width=bbox_width,
                    bbox_height=bbox_height,
                    source_observation_id=observation.observation_id,
                    semantic_attributes={
                        "detected_text": detected_text,
                        "ocr_confidence": confidence,
                    },
                )
            )

        return candidates


# Module-level default instance
ocr_perception_provider = OcrPerceptionProvider()
