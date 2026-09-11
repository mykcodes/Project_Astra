import pytest
import asyncio
import ctypes
import win32gui
import win32con
import win32process
import os
import subprocess
import time
from datetime import datetime

from app.environment.visual.capture import screen_capture_provider
from app.environment.visual.mapper import visual_mapper
from app.environment.visual.tracker import interaction_tracker
from app.interaction.input.mouse_controller import mouse_controller
from app.domain.entities import ScreenPoint, TriState
from app.domain.visual import VisualCaptureError
from app.environment.application.resolver import resolver
from app.environment.awareness import get_awareness_provider

@pytest.mark.asyncio
async def test_live_coordinate_fidelity():
    """
    Live interactive test proving coordinate fidelity.
    """
    # 1. Launch Notepad
    process = subprocess.Popen(["notepad.exe"])
    time.sleep(2)  # Wait for it to open
    
    hwnd = None
    res = resolver.resolve("notepad")
    if res["status"] == "RESOLVED":
        candidate = res["candidate"]
        provider = get_awareness_provider()
        app_info = provider.observe_application(candidate.canonical_name)
        for h in app_info.window_handles:
            try:
                win_info = provider.observe_window(h)
                if win_info.visible == TriState.TRUE:
                    hwnd = h
                    break
            except Exception:
                pass
        
    assert hwnd is not None, "Notepad did not launch or become visible."
    
    try:
        # 2. Position it deterministically
        x, y, w, h = 100, 100, 500, 500
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, x, y, w, h, win32con.SWP_SHOWWINDOW)
        time.sleep(0.5)
        
        # 3. Capture full virtual screen
        obs1 = screen_capture_provider.capture_virtual_screen("live_test_1")
        
        # 4. Verify capture dimensions
        # Expected from GetSystemMetrics in DPI context
        user32 = ctypes.windll.user32
        def get_metrics():
            return (
                user32.GetSystemMetrics(76), # vx
                user32.GetSystemMetrics(77), # vy
                user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0), # vcx
                user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1)  # vcy
            )
        expected_vx, expected_vy, expected_vcx, expected_vcy = mouse_controller._with_dpi_awareness(get_metrics)
        
        assert obs1.width == expected_vcx
        assert obs1.height == expected_vcy
        assert obs1.virtual_offset_x == expected_vx
        assert obs1.virtual_offset_y == expected_vy
        
        # 5. OS window geometry expected region
        rect = win32gui.GetWindowRect(hwnd) # (left, top, right, bottom)
        # Note: GetWindowRect returns logical coords unless we are DPI aware
        # Wrap it in DPI context to get physical coords!
        rect_phys = mouse_controller._with_dpi_awareness(lambda: win32gui.GetWindowRect(hwnd))
        
        win_left, win_top, win_right, win_bottom = rect_phys
        
        # 6. Map known screenshot pixels to ScreenPoint using mapper
        # If notepad is at physical (win_left, win_top), the image pixel should be:
        image_px_x = win_left - obs1.virtual_offset_x
        image_px_y = win_top - obs1.virtual_offset_y
        
        sp = visual_mapper.map_to_screen_point(obs1, image_px_x, image_px_y)
        
        # 7. Verify mapping is consistent with actual window geometry
        assert sp.x == win_left
        assert sp.y == win_top
        
        # 8. Use B.1 MouseController to move to a known point inside Notepad
        target_sp = ScreenPoint(x=win_left + 50, y=win_top + 50)
        
        # Record interaction in tracker to trigger staleness
        interaction_tracker.record_interaction()
        result = mouse_controller.actuate_move(target_sp)
        assert result.get("success"), "Mouse move failed"
        
        # 9. Verify staleness of obs1
        with pytest.raises(VisualCaptureError) as exc:
            visual_mapper.map_to_screen_point(obs1, 0, 0)
        assert exc.value.code == "STALE_OBSERVATION"
        
        # 10. Capture again and verify corresponding screenshot coordinate
        obs2 = screen_capture_provider.capture_virtual_screen("live_test_2")
        
        # Verify the target_sp maps backward to the correct image pixel
        image_px_target_x = target_sp.x - obs2.virtual_offset_x
        image_px_target_y = target_sp.y - obs2.virtual_offset_y
        
        mapped_back_sp = visual_mapper.map_to_screen_point(obs2, image_px_target_x, image_px_target_y)
        assert mapped_back_sp.x == target_sp.x
        assert mapped_back_sp.y == target_sp.y
        
    finally:
        # 11. Clean up Notepad
        process.kill()
        process.communicate()
