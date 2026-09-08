import pytest
from unittest.mock import MagicMock, patch
import ctypes

from app.environment.window.manager import WindowManager

@pytest.fixture
def mock_user32():
    with patch('app.environment.window.manager.ctypes.windll') as mock_windll:
        mock_user32 = MagicMock()
        mock_windll.user32 = mock_user32
        
        # Default behavior
        mock_user32.GetForegroundWindow.return_value = 100
        mock_user32.GetWindowThreadProcessId.return_value = 1234
        mock_user32.AttachThreadInput.return_value = 1
        
        yield mock_user32

@patch('app.environment.window.manager.ctypes.windll.kernel32.GetCurrentThreadId')
def test_restore_and_focus_attaches_thread(mock_get_thread_id, mock_user32):
    mock_get_thread_id.return_value = 5678
    
    manager = WindowManager()
    manager.user32 = mock_user32
    
    # Mock window visibility/minimized state
    manager.is_minimized = MagicMock(return_value=False)
    
    result = manager.restore_and_focus(999)
    
    # Verify the fallback checks
    mock_user32.GetForegroundWindow.assert_called()
    mock_user32.GetWindowThreadProcessId.assert_called_with(100, None)
    
    # Verify AttachThreadInput was called to attach and detach
    mock_user32.AttachThreadInput.assert_any_call(5678, 1234, True)
    mock_user32.SetForegroundWindow.assert_called_with(999)
    mock_user32.AttachThreadInput.assert_any_call(5678, 1234, False)

@patch('app.environment.window.manager.ctypes.windll.kernel32.GetCurrentThreadId')
def test_restore_and_focus_same_thread(mock_get_thread_id, mock_user32):
    # Same thread ID
    mock_get_thread_id.return_value = 1234
    
    manager = WindowManager()
    manager.user32 = mock_user32
    manager.is_minimized = MagicMock(return_value=False)
    
    result = manager.restore_and_focus(999)
    
    # Verify AttachThreadInput was NOT called
    mock_user32.AttachThreadInput.assert_not_called()
    mock_user32.SetForegroundWindow.assert_called_with(999)
