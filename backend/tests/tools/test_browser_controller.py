import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from app.tools.desktop.browser_controller import BrowserController

@pytest.fixture
def mock_playwright():
    with patch('app.tools.desktop.browser_controller.async_playwright') as mock_ap:
        mock_pw = MagicMock()
        mock_ap.return_value.start = AsyncMock(return_value=mock_pw)
        
        mock_browser = MagicMock()
        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.goto = AsyncMock()
        mock_page.evaluate = AsyncMock()
        
        mock_context.on = MagicMock()
        mock_page.on = MagicMock()
        
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_pw.firefox.launch = AsyncMock(return_value=mock_browser)
        mock_pw.webkit.launch = AsyncMock(return_value=mock_browser)
        
        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        
        yield mock_pw

@pytest.mark.asyncio
async def test_launch_browser(mock_playwright):
    controller = BrowserController()
    result = await controller.launch_browser(browser_type="chromium", headless=True)
    
    assert result["success"] is True
    assert controller.browser is not None
    assert controller.context is not None

@pytest.mark.asyncio
async def test_navigate(mock_playwright):
    controller = BrowserController()
    await controller.launch_browser()
    
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    controller.pages.append(mock_page)
    controller.current_page_index = 0
    
    result = await controller.navigate("https://example.com")
    assert result["success"] is True
    mock_page.goto.assert_called_with("https://example.com", wait_until="domcontentloaded")

@pytest.mark.asyncio
async def test_manage_tabs(mock_playwright):
    controller = BrowserController()
    await controller.launch_browser()
    
    result = await controller.manage_tabs("NEW", "https://google.com")
    assert result["success"] is True
    # The actual context.new_page is called
    controller.context.new_page.assert_called()

@pytest.mark.asyncio
async def test_search(mock_playwright):
    controller = BrowserController()
    await controller.launch_browser()
    
    mock_page = MagicMock()
    mock_page.goto = AsyncMock()
    controller.pages.append(mock_page)
    controller.current_page_index = 0
    
    result = await controller.search("test query")
    assert result["success"] is True
    mock_page.goto.assert_called_with("https://www.google.com/search?q=test+query", wait_until="domcontentloaded")
