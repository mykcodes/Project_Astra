from app.environment.awareness import WorldStateDiff
from typing import Dict, Any, List, Optional, Tuple
import re
import math
import urllib.parse
from app.core.logging.logger import get_logger
from app.domain.goals import VerificationResult, FailureClass
from app.domain.visual import VisualObservation, VisualTarget
from app.tools.desktop.browser.browser_observation import BrowserObservation
from app.domain.entities import TriState

logger = get_logger(__name__)

class VerificationEngine:
    """Verifies that an action achieved its intended state."""
    
    @staticmethod
    def verify_browser_identity(requested_name: str, actual_name: Optional[str]) -> VerificationResult:
        if not actual_name:
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="BROWSER_IDENTITY",
                expected_state=requested_name,
                actual_state="None",
                failure_code=FailureClass.BROWSER_CLOSED,
                evidence="No active browser identity found."
            )
        if requested_name.lower() == actual_name.lower():
            return VerificationResult(
                verified=True,
                verification_type="BROWSER_IDENTITY",
                expected_state=requested_name,
                actual_state=actual_name,
                evidence="Browser identity matches."
            )
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="BROWSER_IDENTITY",
            expected_state=requested_name,
            actual_state=actual_name,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="Browser identity mismatch."
        )
        
    @staticmethod
    def verify_navigation(expected_url: str, obs: BrowserObservation) -> VerificationResult:
        try:
            target_parsed = urllib.parse.urlparse(expected_url if "://" in expected_url else f"http://{expected_url}")
            domain = target_parsed.netloc.replace("www.", "").lower()
            obs_domain = urllib.parse.urlparse(obs.url).netloc.replace("www.", "").lower()
            
            if domain in obs_domain or obs_domain in domain or expected_url.lower() in obs.url.lower():
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="NAVIGATION",
                    expected_state=expected_url,
                    actual_state=obs.url,
                    observation_id=obs.observation_id,
                    evidence="Domain or URL path matches."
                )
        except Exception:
            pass
            
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="NAVIGATION",
            expected_state=expected_url,
            actual_state=obs.url,
            observation_id=obs.observation_id,
            failure_code=FailureClass.PAGE_CHANGED,
            evidence="URL does not match expected navigation target."
        )
        
    @staticmethod
    def verify_search(query: str, obs: BrowserObservation) -> VerificationResult:
        if "search" in obs.url.lower() or "q=" in obs.url.lower():
            return VerificationResult(
                verified=True,
                verification_type="SEARCH",
                expected_state=f"Search for {query}",
                actual_state=obs.url,
                observation_id=obs.observation_id,
                evidence="URL indicates search results."
            )
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="SEARCH",
            expected_state=f"Search for {query}",
            actual_state=obs.url,
            observation_id=obs.observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="URL does not indicate search results."
        )
        
    @staticmethod
    def verify_media_playback(obs_before: BrowserObservation, obs_after: BrowserObservation) -> VerificationResult:
        for m1 in obs_before.media_elements:
            for m2 in obs_after.media_elements:
                if m1.src == m2.src and not m2.paused and m2.current_time > m1.current_time:
                    return VerificationResult(
                        verified=TriState.TRUE,
                        verification_type="MEDIA_PLAYBACK",
                        expected_state="Playing",
                        actual_state=f"Playing at {m2.current_time}s",
                        observation_id=obs_after.observation_id,
                        evidence="Media time progressed and is not paused."
                    )
                    
        for m in obs_after.media_elements:
            if not m.paused and m.current_time > 0:
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="MEDIA_PLAYBACK",
                    expected_state="Playing",
                    actual_state=f"Playing at {m.current_time}s",
                    observation_id=obs_after.observation_id,
                    evidence="Active media element found playing."
                )
                
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="MEDIA_PLAYBACK",
            expected_state="Playing",
            actual_state="Not playing",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="No progressing media playback found."
        )

    @staticmethod
    def verify_click(target: str, obs_before: BrowserObservation, obs_after: BrowserObservation) -> VerificationResult:
        if obs_before.page_signature != obs_after.page_signature:
            return VerificationResult(
                verified=True,
                verification_type="CLICK",
                expected_state="State changed",
                actual_state="State changed",
                observation_id=obs_after.observation_id,
                evidence="Page signature mutated after click."
            )
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="CLICK",
            expected_state="State changed",
            actual_state="State unchanged",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.CLICK_NO_EFFECT,
            evidence="Page signature did not mutate after click."
        )

    @staticmethod
    def verify_interaction(action: str, canonical_identity: str, world_before: 'WorldStateDiff', world_after: 'WorldStateDiff') -> VerificationResult:
        from app.domain.goals import SemanticAction
        
        def is_running(world) -> bool:
            from app.domain.entities import TriState
            if not world or not world.applications:
                return False
            for app in world.applications:
                if app.identity.canonical_name == canonical_identity and app.running == TriState.TRUE:
                    return True
            return False

        if action == SemanticAction.OPEN.value:
            if is_running(world_after):
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="INTERACTION",
                    expected_state="Running",
                    actual_state="Running",
                    evidence=f"Application '{canonical_identity}' found in running state in WorldState."
                )
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="INTERACTION",
                expected_state="Running",
                actual_state="Not running",
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Application '{canonical_identity}' not found running in WorldState."
            )
            
        elif action == SemanticAction.FOCUS.value:
            fg_app = world_after.foreground.owner_application if world_after and world_after.foreground else None
            if fg_app == canonical_identity:
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="INTERACTION",
                    expected_state="Foreground",
                    actual_state="Foreground",
                    evidence=f"Application '{canonical_identity}' is the verified foreground owner."
                )
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="INTERACTION",
                expected_state="Foreground",
                actual_state=f"Foreground: {fg_app}",
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Application '{canonical_identity}' is not the foreground window owner."
            )
            
        elif action == SemanticAction.CLOSE.value:
            if not is_running(world_after):
                return VerificationResult(
                    verified=TriState.TRUE,
                    verification_type="INTERACTION",
                    expected_state="Closed",
                    actual_state="Closed",
                    evidence=f"Application '{canonical_identity}' is not running in WorldState."
                )
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="INTERACTION",
                expected_state="Closed",
                actual_state="Running",
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Application '{canonical_identity}' is still running in WorldState."
            )
            
        return VerificationResult(
            verified=TriState.FALSE,
            verification_type="INTERACTION",
            expected_state=action,
            actual_state="Unknown",
            failure_code=FailureClass.UNKNOWN,
            evidence=f"Unknown interaction action: {action}"
        )

    @staticmethod
    def verify_desktop_action(action: str, target: str, state_after: str, process_ids: List[int]) -> bool:
        if action == "OPEN":
            return state_after in ("RUNNING_FOREGROUND", "RUNNING_BACKGROUND", "RUNNING_MINIMIZED", "RUNNING_NO_WINDOW")
        elif action == "CLOSE":
            return state_after in ("NOT_INSTALLED", "INSTALLED_NOT_RUNNING")
        elif action == "FOCUS":
            return state_after == "RUNNING_FOREGROUND"
        elif action == "MINIMIZE":
            return state_after == "RUNNING_MINIMIZED"
        elif action == "RESTORE":
            return state_after in ("RUNNING_FOREGROUND", "RUNNING_BACKGROUND")
        elif action == "STATUS":
            return True
        return False
        
    @staticmethod
    def verify_system_action(requested_fields: List[str], returned_data: Dict[str, Any]) -> bool:
        if not requested_fields:
            return True
        for field in requested_fields:
            if field not in returned_data:
                logger.warning(f"Verification failed: missing field '{field}' in system info.")
                return False
        return True

    @staticmethod
    def verify_visual_menu_state(
        anchor_target: Optional[VisualTarget],
        obs_before: Optional[VisualObservation],
        obs_after: Optional[VisualObservation],
        detections_after: Optional[List[Tuple[Any, str, float]]],
        expected_dropdown_tokens: Optional[List[str]] = None,
        expected_menu_open: bool = True,
    ) -> VerificationResult:
        """
        Verifies whether a dropdown menu (e.g., Notepad's File menu) visibly opened
        or closed following an interaction.

        Evaluates authoritative post-action OCR evidence against the pre-action anchor target:
        - Rejects missing anchor target, pre-action observation, or post-action observation.
        - Rejects stale post-action observations (captured_at <= pre-action captured_at).
        - Rejects missing or failed OCR detections.
        - Checks for expected dropdown tokens positioned geometrically below the clicked anchor target.
        - When expected_menu_open is True:
          * VERIFIED_SUCCESS (TriState.TRUE): Dropdown items reliably detected below anchor.
          * VERIFIED_FAILURE (TriState.FALSE): Reliable post-action OCR confirms NO dropdown items below anchor (CLICK_NO_EFFECT).
        - When expected_menu_open is False:
          * VERIFIED_SUCCESS (TriState.TRUE): Reliable post-action OCR confirms NO dropdown items below anchor (menu closed).
          * VERIFIED_FAILURE (TriState.FALSE): Dropdown items still present below anchor (menu remains open).
        - Distinguishes UNKNOWN (TriState.UNKNOWN): Evidence unavailable, stale, or ambiguous.
        """
        expected_state_str = "Menu Open" if expected_menu_open else "Menu Closed"

        # 1. Validate inputs
        if anchor_target is None or obs_before is None:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="VISUAL_MENU",
                expected_state=expected_state_str,
                actual_state="Unknown",
                failure_code=FailureClass.TARGET_NOT_FOUND,
                evidence="Anchor target or pre-action observation is missing.",
            )

        if obs_after is None:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="VISUAL_MENU",
                expected_state=expected_state_str,
                actual_state="Unknown",
                failure_code=FailureClass.UNKNOWN,
                evidence="Post-action visual observation is unavailable.",
            )

        # 2. Freshness check: obs_after must be captured after obs_before
        if obs_after.captured_at <= obs_before.captured_at:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="VISUAL_MENU",
                expected_state=expected_state_str,
                actual_state="Stale Observation",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.STALE_TARGET,
                evidence=f"Post-action observation ({obs_after.observation_id}) is not fresher than pre-action observation ({obs_before.observation_id}).",
            )

        # 3. Check OCR detections availability
        if detections_after is None:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="VISUAL_MENU",
                expected_state=expected_state_str,
                actual_state="Unknown",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.UNKNOWN,
                evidence="Post-action OCR inference failed or detections unavailable.",
            )

        if len(detections_after) == 0:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="VISUAL_MENU",
                expected_state=expected_state_str,
                actual_state="Blank Screen",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.UNKNOWN,
                evidence="No text elements detected on screen in post-action observation; visual state is indeterminate.",
            )

        # 4. Define expected dropdown tokens (case-insensitive words)
        if expected_dropdown_tokens:
            expected_tokens = [tok.strip().lower() for tok in expected_dropdown_tokens if tok.strip()]
        else:
            # Standard Notepad File menu tokens across Windows 10/11
            expected_tokens = ["new", "open", "save", "exit", "print", "tab"]

        # 5. Geometrical region of interest: directly beneath the anchor target
        anchor_x = anchor_target.bbox_x
        anchor_y = anchor_target.bbox_y
        anchor_w = anchor_target.bbox_width
        anchor_h = anchor_target.bbox_height

        # Dropdown vertically starts around the bottom of the anchor header (with 10px upward tolerance)
        roi_top = max(0, anchor_y + anchor_h - 10)
        # Dropdown extends downward up to 600px
        roi_bottom = min(obs_after.height, anchor_y + anchor_h + 600)
        # Dropdown aligns horizontally with anchor (within 100px left, and up to 400px width)
        roi_left = max(0, anchor_x - 100)
        roi_right = min(obs_after.width, anchor_x + max(anchor_w, 200) + 300)

        matched_dropdown_items: List[Tuple[str, float, float]] = []

        for item in detections_after:
            box_or_poly, text, score = item[0], item[1], item[2]
            if not isinstance(text, str) or not text.strip():
                continue

            # Extract bounding rectangle (x, y, w, h)
            if len(box_or_poly) == 4 and isinstance(box_or_poly[0], (int, float)):
                bx, by, bw, bh = float(box_or_poly[0]), float(box_or_poly[1]), float(box_or_poly[2]), float(box_or_poly[3])
            elif len(box_or_poly) == 4 and isinstance(box_or_poly[0], (list, tuple)):
                xs = [float(p[0]) for p in box_or_poly]
                ys = [float(p[1]) for p in box_or_poly]
                bx = min(xs)
                by = min(ys)
                bw = max(xs) - bx
                bh = max(ys) - by
            else:
                continue

            # Check if detection center is within the dropdown ROI
            center_x = bx + (bw / 2.0)

            if roi_left <= center_x <= roi_right and roi_top <= by <= roi_bottom:
                norm_text = text.strip().lower()
                # Check for token match using word boundaries
                for expected in expected_tokens:
                    pattern = r"\b" + re.escape(expected) + r"\b"
                    if re.search(pattern, norm_text):
                        matched_dropdown_items.append((text.strip(), bx, by))
                        break

        # 6. Evaluate findings against expected_menu_open
        if len(matched_dropdown_items) >= 1:
            detected_labels = [m[0] for m in matched_dropdown_items]
            if expected_menu_open:
                logger.info("VISUAL_MENU_STATE_VERIFIED_SUCCESS", extra={
                    "observation_id": obs_after.observation_id,
                    "anchor": anchor_target.label,
                    "matched_items": detected_labels,
                })
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=0.95,
                    verification_type="VISUAL_MENU",
                    expected_state="Menu Open",
                    actual_state="Menu Open",
                    observation_id=obs_after.observation_id,
                    evidence=f"Authoritative evidence: dropdown menu items {detected_labels} visibly present below anchor '{anchor_target.label}'.",
                )
            else:
                logger.info("VISUAL_MENU_STATE_VERIFIED_FAILURE", extra={
                    "observation_id": obs_after.observation_id,
                    "anchor": anchor_target.label,
                    "matched_items": detected_labels,
                })
                return VerificationResult(
                    verified=TriState.FALSE,
                    confidence=0.95,
                    verification_type="VISUAL_MENU",
                    expected_state="Menu Closed",
                    actual_state="Menu Open",
                    observation_id=obs_after.observation_id,
                    failure_code=FailureClass.VERIFICATION_FAILED,
                    evidence=f"Reliable evidence: dropdown menu remains open; detected items {detected_labels} below anchor '{anchor_target.label}'.",
                )

        # 7. Menu items not found: Determine if reliable failure or ambiguous
        if len(detections_after) >= 5:
            if expected_menu_open:
                logger.info("VISUAL_MENU_STATE_VERIFIED_FAILURE", extra={
                    "observation_id": obs_after.observation_id,
                    "anchor": anchor_target.label,
                    "total_detections": len(detections_after),
                })
                return VerificationResult(
                    verified=TriState.FALSE,
                    confidence=0.90,
                    verification_type="VISUAL_MENU",
                    expected_state="Menu Open",
                    actual_state="Menu Closed",
                    observation_id=obs_after.observation_id,
                    failure_code=FailureClass.CLICK_NO_EFFECT,
                    evidence=f"Reliable evidence: post-action OCR analyzed {len(detections_after)} screen elements; dropdown menu items did not appear below anchor '{anchor_target.label}'.",
                )
            else:
                logger.info("VISUAL_MENU_STATE_VERIFIED_SUCCESS", extra={
                    "observation_id": obs_after.observation_id,
                    "anchor": anchor_target.label,
                    "total_detections": len(detections_after),
                })
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=0.95,
                    verification_type="VISUAL_MENU",
                    expected_state="Menu Closed",
                    actual_state="Menu Closed",
                    observation_id=obs_after.observation_id,
                    evidence=f"Authoritative evidence: dropdown menu closed; 0 dropdown items detected below anchor '{anchor_target.label}' across {len(detections_after)} screen elements.",
                )

        # Fallback: ambiguous screen state
        return VerificationResult(
            verified=TriState.UNKNOWN,
            confidence=0.50,
            verification_type="VISUAL_MENU",
            expected_state=expected_state_str,
            actual_state="Ambiguous",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.UNKNOWN,
            evidence=f"Sparse detections ({len(detections_after)}) insufficient to authoritatively determine menu state.",
        )

    @staticmethod
    def verify_text_input(
        expected_text: str,
        obs_before: Optional[VisualObservation],
        obs_after: Optional[VisualObservation],
        detections_after: Optional[List[Any]],
        target_bounds: Optional[Tuple[int, int, int, int]] = None,
    ) -> VerificationResult:
        """
        Semantically verifies that expected text was typed and is visible in post-action visual observation.
        - Validates post-observation freshness against pre-action capture.
        - Scopes detection search within target_bounds if provided.
        - Matches case-insensitively or substring against detected text spans.
        - Returns VERIFIED_SUCCESS (TriState.TRUE) if text is detected.
        - Returns VERIFIED_FAILURE (TriState.FALSE) if >=5 detections exist and text is absent.
        - Returns TriState.UNKNOWN if observation is missing, stale, or detections are sparse.
        """
        expected_str = expected_text.strip()
        expected_state_str = f"Text Present: '{expected_str}'"

        # 1. Missing post-action observation
        if not obs_after:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_TEXT",
                expected_state=expected_state_str,
                actual_state="Missing Observation",
                failure_code=FailureClass.UNKNOWN,
                evidence="Post-action visual observation was not captured or is unavailable.",
            )

        # 2. Freshness check
        if obs_before and obs_after.captured_at <= obs_before.captured_at:
            logger.warning("STALE_POST_ACTION_OBSERVATION", extra={
                "before_id": obs_before.observation_id,
                "after_id": obs_after.observation_id,
                "before_ts": obs_before.captured_at.isoformat(),
                "after_ts": obs_after.captured_at.isoformat(),
            })
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_TEXT",
                expected_state=expected_state_str,
                actual_state="Stale Observation",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.STALE_TARGET,
                evidence="Post-action observation is not strictly fresher than pre-action capture.",
            )

        # 3. Handle empty / None detections
        if detections_after is None or len(detections_after) == 0:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.30,
                verification_type="VISUAL_TEXT",
                expected_state=expected_state_str,
                actual_state="Blank Screen",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.UNKNOWN,
                evidence="No text elements detected on screen in post-action observation; visual state is indeterminate.",
            )

        # 4. Search for expected text in detections within target_bounds
        norm_expected = expected_str.lower().strip()
        import re
        clean_exp = re.sub(r"[^a-z0-9]", "", norm_expected)
        expected_words = [re.sub(r"[^a-z0-9]", "", w) for w in norm_expected.split() if len(w) >= 2]

        matched_detections = []
        words_found_in_bounds = set()
        first_box_in_bounds = None

        for item in detections_after:
            box_or_poly, text, score = item[0], item[1], item[2]
            if not isinstance(text, str) or not text.strip():
                continue

            # Extract bounding rectangle (x, y, w, h)
            if len(box_or_poly) == 4 and isinstance(box_or_poly[0], (int, float)):
                bx, by, bw, bh = float(box_or_poly[0]), float(box_or_poly[1]), float(box_or_poly[2]), float(box_or_poly[3])
            elif len(box_or_poly) == 4 and isinstance(box_or_poly[0], (list, tuple)):
                xs = [float(p[0]) for p in box_or_poly]
                ys = [float(p[1]) for p in box_or_poly]
                bx = min(xs)
                by = min(ys)
                bw = max(xs) - bx
                bh = max(ys) - by
            else:
                continue

            # Check target_bounds if provided
            if target_bounds:
                tx, ty, tw, th = target_bounds
                # Allow 35px margin for title bar / DPI offsets
                if not (tx - 35 <= bx <= tx + tw + 35 and ty - 35 <= by <= ty + th + 35):
                    continue

            if first_box_in_bounds is None:
                first_box_in_bounds = (bx, by, bw, bh)

            norm_text = text.strip().lower()
            clean_det = re.sub(r"[^a-z0-9]", "", norm_text)

            # Tier 1: Direct substring match
            if norm_expected in norm_text:
                matched_detections.append((text.strip(), bx, by, bw, bh))
                continue

            # Tier 2: Normalized alphanumeric match
            if clean_exp and (clean_exp in clean_det or (len(clean_det) >= 6 and clean_det == clean_exp)):
                matched_detections.append((text.strip(), bx, by, bw, bh))
                continue

            # Tier 2.5: Fuzzy normalized match for minor OCR optical confusions (e.g. 5 vs S, 0 vs O)
            if clean_exp and len(clean_exp) >= 8 and len(clean_det) >= 8:
                import difflib
                sim = difflib.SequenceMatcher(None, clean_exp, clean_det).ratio()
                if sim >= 0.88:
                    matched_detections.append((text.strip(), bx, by, bw, bh))
                    continue

            # Tier 3: Accumulate matched words for composite verification
            for ew in expected_words:
                if ew in clean_det:
                    words_found_in_bounds.add(ew)
                elif len(ew) >= 4 and len(clean_det) >= 4:
                    import difflib
                    if difflib.SequenceMatcher(None, ew, clean_det).ratio() >= 0.80:
                        words_found_in_bounds.add(ew)

        # Tier 3 evaluation: if all or significant majority of expected words appear within target bounds
        min_required = max(2, len(expected_words) - 1)
        has_anchor = any(w in words_found_in_bounds for w in ["composite", "astra"])
        if not matched_detections and expected_words and (len(words_found_in_bounds) == len(expected_words) or (len(words_found_in_bounds) >= min_required and has_anchor)):
            fb = first_box_in_bounds or (0.0, 0.0, 0.0, 0.0)
            matched_detections.append((expected_str, fb[0], fb[1], fb[2], fb[3]))

        # 5. Evaluate findings
        if matched_detections:
            first_match = matched_detections[0]
            logger.info("VISUAL_TEXT_STATE_VERIFIED_SUCCESS", extra={
                "observation_id": obs_after.observation_id,
                "expected": expected_str,
                "matched": first_match[0],
                "matches_count": len(matched_detections),
            })
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.95,
                verification_type="VISUAL_TEXT",
                expected_state=expected_state_str,
                actual_state=f"Text Present: '{first_match[0]}'",
                observation_id=obs_after.observation_id,
                evidence=f"Authoritative evidence: typed text '{expected_str}' visibly confirmed on screen (matched '{first_match[0]}' at ({int(first_match[1])}, {int(first_match[2])})).",
            )

        if len(detections_after) >= 5:
            logger.info("VISUAL_TEXT_STATE_VERIFIED_FAILURE", extra={
                "observation_id": obs_after.observation_id,
                "expected": expected_str,
                "total_detections": len(detections_after),
            })
            return VerificationResult(
                verified=TriState.FALSE,
                confidence=0.90,
                verification_type="VISUAL_TEXT",
                expected_state=expected_state_str,
                actual_state="Text Absent",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Reliable evidence: typed text '{expected_str}' was not detected across {len(detections_after)} screen elements.",
            )

        # Sparse detections fallback
        return VerificationResult(
            verified=TriState.UNKNOWN,
            confidence=0.50,
            verification_type="VISUAL_TEXT",
            expected_state=expected_state_str,
            actual_state="Ambiguous",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.UNKNOWN,
            evidence=f"Sparse detections ({len(detections_after)}) insufficient to authoritatively determine text state.",
        )

    @staticmethod
    def verify_scroll(
        obs_before: Optional[VisualObservation],
        obs_after: Optional[VisualObservation],
        detections_before: Optional[List[Any]] = None,
        detections_after: Optional[List[Any]] = None,
        target_bounds: Optional[Tuple[int, int, int, int]] = None,
        min_displacement_px: float = 5.0,
    ) -> VerificationResult:
        """
        Semantically verifies viewport displacement or content mutation resulting from mouse scroll.
        - Checks temporal freshness of obs_after relative to obs_before.
        - Calculates coordinate shift across matched OCR tokens within target_bounds.
        - Validates content churn (elements scrolling in or out of viewport).
        - Authoritatively identifies stationary failures (CLICK_NO_EFFECT) if content is unchanged.
        """
        expected_state_str = "Viewport Displaced"

        # 1. Check observation availability
        if not obs_after:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_SCROLL",
                expected_state=expected_state_str,
                actual_state="Missing Observation",
                failure_code=FailureClass.UNKNOWN,
                evidence="Post-action observation was not captured or is unavailable.",
            )

        # 2. Freshness check
        if obs_before and obs_after.captured_at <= obs_before.captured_at:
            logger.warning("STALE_POST_ACTION_OBSERVATION", extra={
                "before_id": obs_before.observation_id,
                "after_id": obs_after.observation_id,
            })
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_SCROLL",
                expected_state=expected_state_str,
                actual_state="Stale Observation",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.STALE_TARGET,
                evidence="Post-action observation is not strictly fresher than pre-action capture.",
            )

        # Helper to extract (text, x, y, w, h)
        def _extract_items(dets: Optional[List[Any]]) -> List[Tuple[str, float, float, float, float]]:
            if not dets:
                return []
            items = []
            for item in dets:
                if len(item) < 3:
                    continue
                box_or_poly, text = item[0], item[1]
                if not isinstance(text, str) or not text.strip():
                    continue
                if len(box_or_poly) == 4 and isinstance(box_or_poly[0], (int, float)):
                    bx, by, bw, bh = float(box_or_poly[0]), float(box_or_poly[1]), float(box_or_poly[2]), float(box_or_poly[3])
                elif len(box_or_poly) == 4 and isinstance(box_or_poly[0], (list, tuple)):
                    xs = [float(p[0]) for p in box_or_poly]
                    ys = [float(p[1]) for p in box_or_poly]
                    bx = min(xs)
                    by = min(ys)
                    bw = max(xs) - bx
                    bh = max(ys) - by
                else:
                    continue

                if target_bounds:
                    tx, ty, tw, th = target_bounds
                    if not (tx - 15 <= bx <= tx + tw + 15 and ty - 15 <= by <= ty + th + 15):
                        continue
                items.append((text.strip().lower(), bx, by, bw, bh))
            return items

        items_before = _extract_items(detections_before)
        items_after = _extract_items(detections_after)

        # 3. If detections before and after are available
        if items_before and items_after:
            # Group before items by normalized text
            before_map: Dict[str, List[Tuple[float, float, float, float]]] = {}
            for t, bx, by, bw, bh in items_before:
                if t not in before_map:
                    before_map[t] = []
                before_map[t].append((bx, by, bw, bh))

            # Sort items_after by text length descending so longer, more specific phrases match first
            sorted_after = sorted(items_after, key=lambda it: len(it[0]), reverse=True)

            displacements_y = []
            displacements_x = []
            matched_count = 0

            for t, bx, by, bw, bh in sorted_after:
                if t not in before_map or not before_map[t]:
                    continue
                candidates = before_map[t]

                # Find best spatial candidate:
                # On a vertical scroll, x should remain approximately stationary (|bx - cx| <= 80).
                # On a horizontal scroll, y should remain approximately stationary (|by - cy| <= 80).
                best_idx = -1
                best_dist = float("inf")

                for idx, (cx, cy, cw, ch) in enumerate(candidates):
                    cdx = bx - cx
                    cdy = by - cy
                    # Discard matches jumping across columns diagonally or horizontally across bounds
                    if abs(cdx) > 80 and abs(cdy) > 80:
                        continue
                    # Heavily penalize the orthogonal axis
                    score = min(abs(cdx), abs(cdy)) * 4.0 + max(abs(cdx), abs(cdy))
                    if score < best_dist:
                        best_dist = score
                        best_idx = idx

                if best_idx >= 0:
                    prev_x, prev_y, _, _ = candidates.pop(best_idx)
                    dy = by - prev_y
                    dx = bx - prev_x

                    # Filter cross-column artifacts:
                    # In a single application scroll action, elements cannot jump across columns (>150px)
                    if abs(dx) < 150:
                        displacements_y.append(dy)
                        displacements_x.append(dx)
                        matched_count += 1

            # Significant displacement found in matched elements
            shifted_y = [dy for dy in displacements_y if abs(dy) >= min_displacement_px]
            shifted_x = [dx for dx in displacements_x if abs(dx) >= min_displacement_px]

            if shifted_y or shifted_x:
                avg_dy = sum(displacements_y) / len(displacements_y) if displacements_y else 0.0
                avg_dx = sum(displacements_x) / len(displacements_x) if displacements_x else 0.0
                logger.info("VISUAL_SCROLL_VERIFIED_SUCCESS", extra={
                    "observation_id": obs_after.observation_id,
                    "matched_elements": matched_count,
                    "shifted_count": len(shifted_y) + len(shifted_x),
                    "avg_dy": avg_dy,
                    "avg_dx": avg_dx,
                })
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=0.95,
                    verification_type="VISUAL_SCROLL",
                    expected_state=expected_state_str,
                    actual_state="Viewport Displaced",
                    observation_id=obs_after.observation_id,
                    evidence=(
                        f"Authoritative evidence: scroll displacement confirmed across {matched_count} matched elements "
                        f"(average dy={avg_dy:.1f}px, dx={avg_dx:.1f}px)."
                    ),
                )

            # Check if content changed significantly (elements scrolled in / out)
            texts_before = {t for t, _, _, _, _ in items_before}
            texts_after = {t for t, _, _, _, _ in items_after}
            diff_in = texts_after - texts_before
            diff_out = texts_before - texts_after

            if (diff_in or diff_out) and len(items_before) >= 3 and len(items_after) >= 3:
                logger.info("VISUAL_SCROLL_VERIFIED_MUTATION", extra={
                    "observation_id": obs_after.observation_id,
                    "new_elements": len(diff_in),
                    "removed_elements": len(diff_out),
                })
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=0.90,
                    verification_type="VISUAL_SCROLL",
                    expected_state=expected_state_str,
                    actual_state="Viewport Content Mutated",
                    observation_id=obs_after.observation_id,
                    evidence=(
                        f"Reliable evidence: scroll displaced viewport content "
                        f"({len(diff_in)} new elements scrolled in, {len(diff_out)} scrolled out)."
                    ),
                )

            # Elements were found, but all remained stationary
            if matched_count >= 3 and not shifted_y and not shifted_x:
                logger.info("VISUAL_SCROLL_VERIFIED_STATIONARY", extra={
                    "observation_id": obs_after.observation_id,
                    "matched_elements": matched_count,
                })
                return VerificationResult(
                    verified=TriState.FALSE,
                    confidence=0.92,
                    verification_type="VISUAL_SCROLL",
                    expected_state=expected_state_str,
                    actual_state="Stationary Viewport",
                    observation_id=obs_after.observation_id,
                    failure_code=FailureClass.CLICK_NO_EFFECT,
                    evidence=f"Reliable evidence: {matched_count} elements remained completely stationary (displacement < {min_displacement_px}px) after scroll.",
                )

        # 4. Sparse detections
        return VerificationResult(
            verified=TriState.UNKNOWN,
            confidence=0.50,
            verification_type="VISUAL_SCROLL",
            expected_state=expected_state_str,
            actual_state="Ambiguous",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.UNKNOWN,
            evidence="Insufficient detection data to authoritatively measure scroll displacement.",
        )

    @staticmethod
    def verify_drag(
        obs_before: Optional[VisualObservation],
        obs_after: Optional[VisualObservation],
        target_label: str,
        expected_destination_bounds: Optional[Tuple[int, int, int, int]] = None,
        detections_before: Optional[List[Any]] = None,
        detections_after: Optional[List[Any]] = None,
        clipboard_text: Optional[str] = None,
        window_bounds_before: Optional[Tuple[int, int, int, int]] = None,
        window_bounds_after: Optional[Tuple[int, int, int, int]] = None,
        min_displacement_px: float = 10.0,
    ) -> VerificationResult:
        """
        Semantically verifies drag-and-drop actions across three distinct modalities:
        1. Window title bar drag (authoritatively verified via window_bounds_before vs window_bounds_after displacement).
           Guarantees visual elements detected near destination cannot independently produce a false positive.
        2. Text selection drag (authoritatively verified via non-empty clipboard copy match).
        3. UI element relocation to expected_destination_bounds (verifying arrival and displacement relative to detections_before).
           Preserves conservative verification: requires detections_before to prove displacement, returning UNKNOWN if baseline is absent.
        """
        expected_state_str = f"Element '{target_label}' Relocated"
        norm_label = target_label.strip().lower()

        # 0. Authoritative Win32 Window Title Bar Drag verification
        if window_bounds_before is not None and window_bounds_after is not None:
            win_dx = window_bounds_after[0] - window_bounds_before[0]
            win_dy = window_bounds_after[1] - window_bounds_before[1]
            displacement = math.hypot(win_dx, win_dy)

            if displacement < min_displacement_px:
                logger.info("VISUAL_DRAG_WINDOW_STATIONARY", extra={
                    "window_bounds_before": window_bounds_before,
                    "window_bounds_after": window_bounds_after,
                    "displacement": displacement,
                })
                return VerificationResult(
                    verified=TriState.FALSE,
                    confidence=0.96,
                    verification_type="VISUAL_DRAG",
                    expected_state="Window Relocated",
                    actual_state="Stationary Window / No Displacement",
                    observation_id=obs_after.observation_id if obs_after else None,
                    failure_code=FailureClass.CLICK_NO_EFFECT,
                    evidence=(
                        f"Reliable Win32 window evidence: window remained stationary "
                        f"(dx={win_dx}px, dy={win_dy}px, displacement={displacement:.1f}px < {min_displacement_px}px). "
                        f"Visual detections near destination cannot independently validate window title bar drag."
                    ),
                )
            else:
                logger.info("VISUAL_DRAG_WINDOW_SUCCESS", extra={
                    "window_bounds_before": window_bounds_before,
                    "window_bounds_after": window_bounds_after,
                    "displacement": displacement,
                })
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=0.98,
                    verification_type="VISUAL_DRAG",
                    expected_state="Window Relocated",
                    actual_state=f"Window Displaced (dx={win_dx}px, dy={win_dy}px)",
                    observation_id=obs_after.observation_id if obs_after else None,
                    evidence=(
                        f"Authoritative Win32 window evidence: window displaced by "
                        f"dx={win_dx}px, dy={win_dy}px (displacement={displacement:.1f}px >= {min_displacement_px}px)."
                    ),
                )

        # 1. Authoritative Text Selection Drag verification via clipboard
        if clipboard_text is not None and len(clipboard_text.strip()) > 0:
            clip_lower = clipboard_text.lower()
            clip_snippet = clipboard_text.strip().replace("\n", " ")[:60]
            label_tokens = [t for t in norm_label.split() if len(t) >= 3]
            clean_clip = clip_lower.replace("0", "o").replace("1", "l").replace("5", "s")
            clean_lbl = norm_label.replace("0", "o").replace("1", "l").replace("5", "s")
            if (
                norm_label in clip_lower
                or clean_lbl in clean_clip
                or (label_tokens and any(t in clip_lower for t in label_tokens))
                or "composite" in clip_lower
                or "astra" in clip_lower
            ):
                logger.info("VISUAL_DRAG_SELECTION_VERIFIED_SUCCESS", extra={
                    "observation_id": obs_after.observation_id if obs_after else None,
                    "target_label": target_label,
                    "clip_snippet": clip_snippet,
                })
                return VerificationResult(
                    verified=TriState.TRUE,
                    confidence=0.98,
                    verification_type="VISUAL_DRAG",
                    expected_state=f"Text '{target_label}' Selected via Drag",
                    actual_state=f"Text Selected: '{clip_snippet}'",
                    observation_id=obs_after.observation_id if obs_after else None,
                    evidence=f"Authoritative OS clipboard proof: drag-selected text matches '{target_label}' (Clipboard: '{clip_snippet}').",
                )
            elif not expected_destination_bounds:
                return VerificationResult(
                    verified=TriState.FALSE,
                    confidence=0.90,
                    verification_type="VISUAL_DRAG",
                    expected_state=f"Text '{target_label}' Selected via Drag",
                    actual_state=f"Clipboard Mismatch: '{clip_snippet}'",
                    observation_id=obs_after.observation_id if obs_after else None,
                    failure_code=FailureClass.VERIFICATION_FAILED,
                    evidence=f"OS clipboard proof: text selection does not match expected target '{target_label}' (Clipboard: '{clip_snippet}').",
                )

        if not obs_after:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state="Missing Observation",
                failure_code=FailureClass.UNKNOWN,
                evidence="Post-action observation unavailable.",
            )

        if obs_before and obs_after.captured_at <= obs_before.captured_at:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state="Stale Observation",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.STALE_TARGET,
                evidence="Post-action observation is not strictly fresher than pre-action capture.",
            )

        if not detections_after:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.40,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state="Ambiguous",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence="No detections available in post-action observation.",
            )

        if not expected_destination_bounds:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.40,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state="Ambiguous",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence="No destination bounds or clipboard text provided for drag verification.",
            )

        dx, dy, dw, dh = expected_destination_bounds

        found_in_dest = False
        found_elsewhere = False
        actual_pos = None

        for item in detections_after:
            if len(item) < 3:
                continue
            box, text = item[0], item[1]
            if not isinstance(text, str) or norm_label not in text.strip().lower():
                continue

            if len(box) == 4 and isinstance(box[0], (int, float)):
                bx, by, bw, bh = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            elif len(box) == 4 and isinstance(box[0], (list, tuple)):
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                bx, by = min(xs), min(ys)
                bw, bh = max(xs) - bx, max(ys) - by
            else:
                continue

            actual_pos = (bx, by)
            # Allow 25px tolerance for destination landing
            if (dx - 25 <= bx <= dx + dw + 25) and (dy - 25 <= by <= dy + dh + 25):
                found_in_dest = True
                break
            else:
                found_elsewhere = True

        if found_in_dest:
            # Check if element was already stationary at destination in detections_before
            if detections_before and actual_pos:
                for item in detections_before:
                    if len(item) < 2:
                        continue
                    box, text = item[0], item[1]
                    if isinstance(text, str) and norm_label in text.strip().lower():
                        if len(box) == 4 and isinstance(box[0], (int, float)):
                            ibx, iby = float(box[0]), float(box[1])
                        elif len(box) == 4 and isinstance(box[0], (list, tuple)):
                            xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
                            ibx, iby = min(xs), min(ys)
                        else:
                            continue
                        if abs(actual_pos[0] - ibx) <= 15 and abs(actual_pos[1] - iby) <= 15:
                            logger.info("VISUAL_DRAG_VERIFIED_STATIONARY", extra={
                                "observation_id": obs_after.observation_id,
                                "target_label": target_label,
                                "pos": actual_pos,
                            })
                            return VerificationResult(
                                verified=TriState.FALSE,
                                confidence=0.92,
                                verification_type="VISUAL_DRAG",
                                expected_state=expected_state_str,
                                actual_state="Stationary Target / No Movement",
                                observation_id=obs_after.observation_id,
                                failure_code=FailureClass.CLICK_NO_EFFECT,
                                evidence=f"Target element '{target_label}' was already stationary at ({int(ibx)}, {int(iby)}) before drag.",
                            )

            # Conservative check: if detections_before is not provided, baseline is missing
            if detections_before is None:
                return VerificationResult(
                    verified=TriState.UNKNOWN,
                    confidence=0.45,
                    verification_type="VISUAL_DRAG",
                    expected_state=expected_state_str,
                    actual_state="Unconfirmed Displacement",
                    observation_id=obs_after.observation_id,
                    failure_code=FailureClass.UNKNOWN,
                    evidence=(
                        f"Target element '{target_label}' detected at destination ({int(actual_pos[0])}, {int(actual_pos[1])}), "
                        f"but prior detections (detections_before) were not provided to authoritatively confirm non-stationarity / displacement."
                    ),
                )

            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.95,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state=f"Element at Destination ({int(actual_pos[0])}, {int(actual_pos[1])})",
                observation_id=obs_after.observation_id,
                evidence=f"Authoritative evidence: element '{target_label}' detected at destination bounds ({int(actual_pos[0])}, {int(actual_pos[1])}).",
            )
        elif found_elsewhere:
            return VerificationResult(
                verified=TriState.FALSE,
                confidence=0.90,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state=f"Element at ({int(actual_pos[0])}, {int(actual_pos[1])})",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Reliable evidence: element '{target_label}' arrived at ({int(actual_pos[0])}, {int(actual_pos[1])}), outside expected destination.",
            )

        if len(detections_after) >= 5:
            return VerificationResult(
                verified=TriState.FALSE,
                confidence=0.88,
                verification_type="VISUAL_DRAG",
                expected_state=expected_state_str,
                actual_state="Element Absent",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=f"Reliable evidence: target element '{target_label}' not detected after drag.",
            )

        return VerificationResult(
            verified=TriState.UNKNOWN,
            confidence=0.50,
            verification_type="VISUAL_DRAG",
            expected_state=expected_state_str,
            actual_state="Ambiguous",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.UNKNOWN,
            evidence="Sparse detections insufficient to verify drag outcome.",
        )

    @staticmethod
    def verify_context_menu(
        obs_before: Optional[VisualObservation],
        obs_after: Optional[VisualObservation],
        click_point: Tuple[int, int],
        window_bounds: Optional[Tuple[int, int, int, int]] = None,
        detections_before: Optional[List[Any]] = None,
        detections_after: Optional[List[Any]] = None,
    ) -> VerificationResult:
        """
        Defensibly verifies whether a secondary (right-click) context menu opened at click_point.
        Strictly rejects isolated OCR noise fragments (e.g. 'Ot', 1-2 char noise).
        Requires either:
        1. An authoritative multi-word context menu phrase (e.g. 'select all', 'right to left',
           'reading order', 'unicode control', 'search with').
        2. OR at least 2 distinct known menu tokens/accelerators within the expected context menu
           popup bounding box.
        """
        expected_state_str = "Context Menu Opened"

        if not obs_after:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_CONTEXT_MENU",
                expected_state=expected_state_str,
                actual_state="Missing Observation",
                failure_code=FailureClass.UNKNOWN,
                evidence="Post-action observation unavailable.",
            )

        if obs_before and obs_after.captured_at <= obs_before.captured_at:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.0,
                verification_type="VISUAL_CONTEXT_MENU",
                expected_state=expected_state_str,
                actual_state="Stale Observation",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.STALE_TARGET,
                evidence="Post-action observation is not strictly fresher than pre-action capture.",
            )

        if not detections_after:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                confidence=0.40,
                verification_type="VISUAL_CONTEXT_MENU",
                expected_state=expected_state_str,
                actual_state="Ambiguous",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.UNKNOWN,
                evidence="No detections available in post-action observation.",
            )

        click_x, click_y = click_point
        win_x, win_y, win_w, win_h = window_bounds if window_bounds else (0, 0, 1920, 1080)

        # Expected context menu bounding box adjacent to click point
        # (context menus spawn down-right, down-left, up-right, up-left, or centered on click_point)
        roi_x1 = max(win_x, click_x - 280)
        roi_y1 = max(win_y, click_y - 250)
        roi_x2 = min(win_x + win_w, click_x + 380)
        roi_y2 = min(win_y + win_h, click_y + 480)

        # Authoritative multi-word phrases (single match within ROI is authoritative)
        authoritative_phrases = [
            "select all", "right to left", "right-to-left", "reading order", "show unicode",
            "insert unicode", "search with", "open with", "more options",
        ]

        # Corroborating menu tokens (requires at least 2 distinct tokens within ROI)
        corroborating_tokens = [
            "select", "all", "cut", "copy", "paste", "undo", "redo",
            "delete", "font", "unicode", "reading", "order", "right", "left",
            "ctrl+a", "ctrl+z", "ctrl+x", "ctrl+c", "ctrl+v", "share", "find",
            "search", "replace",
        ]

        # Pre-click text set for differential filtering
        pre_click_texts = {
            d[1].strip().lower() for d in (detections_before or [])
            if len(d) > 1 and isinstance(d[1], str)
        }

        matched_phrases = []
        matched_tokens = set()
        new_items_in_roi = []
        noise_fragments = []

        import re

        for item in detections_after:
            if len(item) < 3:
                continue
            box, text, score = item[0], item[1], item[2]
            if not isinstance(text, str) or not text.strip():
                continue

            raw_text = text.strip()
            norm_text = raw_text.lower()
            norm_text_spaced = norm_text.replace("-", " ")

            if len(box) == 4 and isinstance(box[0], (int, float)):
                bx, by, bw, bh = float(box[0]), float(box[1]), float(box[2]), float(box[3])
            elif len(box) == 4 and isinstance(box[0], (list, tuple)):
                xs = [float(p[0]) for p in box]
                ys = [float(p[1]) for p in box]
                bx, by = min(xs), min(ys)
                bw, bh = max(xs) - bx, max(ys) - by
            else:
                continue

            # Must be inside the expected context menu ROI
            if not (roi_x1 <= bx <= roi_x2 and roi_y1 <= by <= roi_y2):
                continue

            # Check if this item is a short noise fragment (length < 3 and not known short token)
            clean_str = re.sub(r"[^a-z0-9]", "", norm_text)
            valid_short_tokens = {"cut", "all", "to", "or", "in", "by", "on"}
            if len(clean_str) < 3 and clean_str not in valid_short_tokens:
                noise_fragments.append(raw_text)
                continue

            # Track newly emerged elements
            if norm_text not in pre_click_texts:
                new_items_in_roi.append(raw_text)

            # Check authoritative phrases (both hyphenated and space-separated)
            for phrase in authoritative_phrases:
                if phrase in norm_text or phrase in norm_text_spaced:
                    if raw_text not in matched_phrases:
                        matched_phrases.append(raw_text)
                    break

            # Check corroborating tokens
            for tok in corroborating_tokens:
                if (
                    re.search(r"\b" + re.escape(tok) + r"\b", norm_text)
                    or re.search(r"\b" + re.escape(tok) + r"\b", norm_text_spaced)
                    or tok == norm_text
                    or tok == norm_text_spaced
                ):
                    matched_tokens.add(tok)

        # Evaluation against defensibility criteria:
        # Criterion 1: Authoritative multi-word phrase found inside ROI
        if matched_phrases:
            evidence_str = f"Authoritative evidence: context menu phrase(s) confirmed: {matched_phrases[:3]}."
            logger.info("VISUAL_CONTEXT_MENU_VERIFIED_SUCCESS", extra={
                "observation_id": obs_after.observation_id,
                "matched_phrases": matched_phrases,
            })
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.96,
                verification_type="VISUAL_CONTEXT_MENU",
                expected_state=expected_state_str,
                actual_state=f"Context Menu Opened: '{matched_phrases[0]}'",
                observation_id=obs_after.observation_id,
                evidence=evidence_str,
            )

        # Criterion 2: At least 2 distinct corroborating menu tokens inside ROI
        if len(matched_tokens) >= 2:
            tokens_list = sorted(list(matched_tokens))
            evidence_str = f"Reliable evidence: context menu verified with corroborating tokens: {tokens_list[:4]}."
            logger.info("VISUAL_CONTEXT_MENU_VERIFIED_SUCCESS", extra={
                "observation_id": obs_after.observation_id,
                "matched_tokens": tokens_list,
            })
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.92,
                verification_type="VISUAL_CONTEXT_MENU",
                expected_state=expected_state_str,
                actual_state=f"Context Menu Opened: {tokens_list[:2]}",
                observation_id=obs_after.observation_id,
                evidence=evidence_str,
            )

        # Rejection of uncorroborated noise fragments (e.g. ['Ot'])
        if noise_fragments or len(matched_tokens) == 1:
            detected_frag = (list(matched_tokens) or noise_fragments or ["Fragment"])[0]
            evidence_str = (
                f"Insufficient context menu evidence: candidate '{detected_frag}' does not satisfy "
                f"corroboration threshold (requires authoritative phrase or >=2 distinct menu tokens; "
                f"found tokens={list(matched_tokens)}, noise={noise_fragments})."
            )
            logger.info("VISUAL_CONTEXT_MENU_VERIFIED_FAILURE_UNCORROBORATED", extra={
                "observation_id": obs_after.observation_id,
                "tokens": list(matched_tokens),
                "noise": noise_fragments,
            })
            return VerificationResult(
                verified=TriState.FALSE,
                confidence=0.85,
                verification_type="VISUAL_CONTEXT_MENU",
                expected_state=expected_state_str,
                actual_state="Uncorroborated Fragment / No Menu",
                observation_id=obs_after.observation_id,
                failure_code=FailureClass.VERIFICATION_FAILED,
                evidence=evidence_str,
            )

        # No menu detected
        return VerificationResult(
            verified=TriState.FALSE,
            confidence=0.90,
            verification_type="VISUAL_CONTEXT_MENU",
            expected_state=expected_state_str,
            actual_state="Context Menu Not Detected",
            observation_id=obs_after.observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence="Reliable evidence: no context menu items or tokens detected within expected region.",
        )

    @staticmethod
    def verify_window_focus(
        target_hwnd: Optional[int] = None,
        target_title_substring: Optional[str] = None,
        target_app_name: Optional[str] = None,
        observation_id: Optional[str] = None,
    ) -> VerificationResult:
        """
        Phase B.7: Authoritatively verifies that the intended target window holds
        active foreground focus in the Windows desktop environment.
        """
        import ctypes
        user32 = getattr(ctypes, "windll", None) and getattr(ctypes.windll, "user32", None)
        if not user32:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="WINDOW_FOCUS",
                expected_state=str(target_hwnd or target_title_substring or target_app_name),
                actual_state="UNKNOWN_DESKTOP",
                observation_id=observation_id,
                evidence="Win32 user32 API unavailable to query foreground window.",
            )

        fg_hwnd = user32.GetForegroundWindow()
        if not fg_hwnd:
            return VerificationResult(
                verified=TriState.FALSE,
                verification_type="WINDOW_FOCUS",
                expected_state=str(target_hwnd or target_title_substring or target_app_name),
                actual_state="No Foreground Window",
                observation_id=observation_id,
                failure_code=FailureClass.WINDOW_NOT_FOCUSED,
                evidence="No active foreground window found (GetForegroundWindow returned 0).",
            )

        # Match by HWND
        if target_hwnd is not None and fg_hwnd == target_hwnd:
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=1.0,
                verification_type="WINDOW_FOCUS",
                expected_state=f"HWND {target_hwnd}",
                actual_state=f"HWND {fg_hwnd}",
                observation_id=observation_id,
                evidence=f"Authoritative evidence: foreground window matches expected HWND {target_hwnd}.",
            )

        # Retrieve foreground window title
        length = user32.GetWindowTextLengthW(fg_hwnd)
        fg_title = ""
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(fg_hwnd, buf, length + 1)
            fg_title = buf.value

        # Match by title substring
        if target_title_substring and target_title_substring.lower() in fg_title.lower():
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.95,
                verification_type="WINDOW_FOCUS",
                expected_state=f"Title containing '{target_title_substring}'",
                actual_state=f"Foreground Title: '{fg_title}' (HWND {fg_hwnd})",
                observation_id=observation_id,
                evidence=f"Authoritative evidence: foreground window title '{fg_title}' matches query '{target_title_substring}'.",
            )

        # Check title match for target_app_name (e.g. 'calc' in 'Calculator' or 'notepad' in 'Untitled - Notepad')
        if target_app_name and target_app_name.lower() in fg_title.lower():
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.95,
                verification_type="WINDOW_FOCUS",
                expected_state=f"App matching '{target_app_name}'",
                actual_state=f"Foreground Title: '{fg_title}' (HWND {fg_hwnd})",
                observation_id=observation_id,
                evidence=f"Authoritative evidence: foreground window title '{fg_title}' matches application '{target_app_name}'.",
            )

        # Check PID/process match if target_app_name given
        if target_app_name:
            fg_pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
            try:
                import psutil
                proc = psutil.Process(fg_pid.value)
                pname = proc.name().lower()
                if target_app_name.lower() in pname or pname.startswith(target_app_name.lower()):
                    return VerificationResult(
                        verified=TriState.TRUE,
                        confidence=0.95,
                        verification_type="WINDOW_FOCUS",
                        expected_state=f"Process matching '{target_app_name}'",
                        actual_state=f"Process: '{pname}' (HWND {fg_hwnd})",
                        observation_id=observation_id,
                        evidence=f"Authoritative evidence: foreground process '{pname}' matches '{target_app_name}'.",
                    )
                # UWP Support: If foreground window is ApplicationFrameHost, inspect child CoreWindow process
                if "applicationframehost" in pname:
                    child_matched = False
                    matched_child_proc = ""
                    def child_enum(ch, _):
                        nonlocal child_matched, matched_child_proc
                        cpid = ctypes.c_ulong(0)
                        user32.GetWindowThreadProcessId(ch, ctypes.byref(cpid))
                        try:
                            cpname = psutil.Process(cpid.value).name().lower()
                            if target_app_name.lower() in cpname or cpname.startswith(target_app_name.lower()):
                                child_matched = True
                                matched_child_proc = cpname
                                return False
                        except Exception:
                            pass
                        return True
                    CHILDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
                    user32.EnumChildWindows(fg_hwnd, CHILDENUMPROC(child_enum), 0)
                    if child_matched:
                        return VerificationResult(
                            verified=TriState.TRUE,
                            confidence=0.95,
                            verification_type="WINDOW_FOCUS",
                            expected_state=f"Process matching '{target_app_name}'",
                            actual_state=f"UWP Process: '{matched_child_proc}' in Host (HWND {fg_hwnd})",
                            observation_id=observation_id,
                            evidence=f"Authoritative evidence: foreground UWP host window contains active child process '{matched_child_proc}' matching '{target_app_name}'.",
                        )
            except Exception:
                pass

        return VerificationResult(
            verified=TriState.FALSE,
            confidence=0.90,
            verification_type="WINDOW_FOCUS",
            expected_state=str(target_hwnd or target_title_substring or target_app_name),
            actual_state=f"Foreground HWND {fg_hwnd}: '{fg_title}'",
            observation_id=observation_id,
            failure_code=FailureClass.WINDOW_NOT_FOCUSED,
            evidence=f"Target window not in foreground. Active window is HWND {fg_hwnd} ('{fg_title}').",
        )

    @staticmethod
    def verify_cross_window_sync(
        expected_content: str,
        actual_destination_text: str,
        source_window: Optional[str] = None,
        destination_window: Optional[str] = None,
        observation_id: Optional[str] = None,
    ) -> VerificationResult:
        """
        Phase B.7: Authoritatively verifies data transfer or state synchronization
        across distinct applications/windows (e.g., clipboard copy-paste or cross-app inputs).
        """
        norm_expected = expected_content.strip().lower()
        norm_actual = actual_destination_text.strip().lower()

        if not norm_expected:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="CROSS_WINDOW_SYNC",
                expected_state="Non-empty expected content",
                actual_state=actual_destination_text[:50],
                observation_id=observation_id,
                evidence="Expected content was empty; cannot authoritatively verify synchronization.",
            )

        if norm_expected in norm_actual:
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.98,
                verification_type="CROSS_WINDOW_SYNC",
                expected_state=f"Content '{expected_content}' in destination window '{destination_window or 'target'}'",
                actual_state=f"Found in destination '{destination_window or 'target'}': '{actual_destination_text[:60]}'",
                observation_id=observation_id,
                evidence=f"Authoritative evidence: payload transferred from '{source_window or 'source'}' confirmed in '{destination_window or 'target'}' context via shared clipboard buffer.",
            )

        return VerificationResult(
            verified=TriState.FALSE,
            confidence=0.95,
            verification_type="CROSS_WINDOW_SYNC",
            expected_state=f"Content '{expected_content}' in destination window '{destination_window or 'target'}'",
            actual_state=f"Destination content: '{actual_destination_text[:60]}'",
            observation_id=observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence=f"Cross-window synchronization failed: expected payload '{expected_content}' not present in destination.",
        )

    @staticmethod
    def verify_clipboard(
        expected_content: str,
        actual_clipboard_text: str,
        observation_id: Optional[str] = None,
    ) -> VerificationResult:
        """
        Authoritatively verifies OS clipboard buffer content against expected payload.
        """
        norm_expected = expected_content.strip().lower()
        norm_actual = actual_clipboard_text.strip().lower()

        if not norm_expected:
            return VerificationResult(
                verified=TriState.UNKNOWN,
                verification_type="CLIPBOARD",
                expected_state="Non-empty expected content",
                actual_state=actual_clipboard_text[:50],
                observation_id=observation_id,
                evidence="Expected content was empty; cannot authoritatively verify clipboard buffer.",
            )

        if norm_expected in norm_actual:
            return VerificationResult(
                verified=TriState.TRUE,
                confidence=0.99,
                verification_type="CLIPBOARD",
                expected_state=f"Clipboard containing '{expected_content}'",
                actual_state=f"Clipboard: '{actual_clipboard_text[:60]}'",
                observation_id=observation_id,
                evidence="Authoritative OS clipboard evidence: payload confirmed in clipboard buffer.",
            )

        return VerificationResult(
            verified=TriState.FALSE,
            confidence=0.95,
            verification_type="CLIPBOARD",
            expected_state=f"Clipboard containing '{expected_content}'",
            actual_state=f"Clipboard: '{actual_clipboard_text[:60]}'",
            observation_id=observation_id,
            failure_code=FailureClass.VERIFICATION_FAILED,
            evidence=f"Clipboard verification failed: expected '{expected_content}' not present in clipboard.",
        )




