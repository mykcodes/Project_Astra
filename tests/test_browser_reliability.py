import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_observation_ids_are_unique():
    from app.tools.desktop.browser.browser_observation import extract_observation
    page = AsyncMock()
    page.url = "http://test"
    page.title = AsyncMock(return_value="Test")
    async def mock_evaluate(script, *args):
        if "iframe[src*" in script: return False
        if "querySelectorAll('button" in script: return [{"tag": "button", "role": "button", "name": "Test", "href": "", "is_visible": True, "is_enabled": True}]
        if "querySelectorAll('video" in script: return []
        if "iframe" in script: return 0
        return []
    page.evaluate = mock_evaluate
    obs1 = await extract_observation(page)
    obs2 = await extract_observation(page)
    assert obs1.observation_id != obs2.observation_id
    
@pytest.mark.asyncio
async def test_stale_target_is_not_reused():
    from app.tools.desktop.browser.browser_resolver import browser_resolver
    from app.tools.desktop.browser.browser_observation import BrowserObservation, BrowserElement
    obs = BrowserObservation(observation_id="123", url="", title="", elements=[BrowserElement(id="ast-123-0", tag="a", role="link", name="test")])
    res = await browser_resolver.resolve("ast-old-0", obs)
    assert res is None

@pytest.mark.asyncio
async def test_media_playback_verification():
    from app.tools.desktop.browser.browser_provider import browser_provider
    from app.tools.desktop.browser.browser_observation import BrowserObservation, BrowserElement, MediaElement
    
    async def mock_observe():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return {"success": True, "observation": BrowserObservation(observation_id="1", url="", title="", elements=[], media_elements=[MediaElement(tag="video", src="vid", paused=True, current_time=0.0, duration=10.0, ended=False, ready_state=4, muted=False, volume=1.0)])}
        elif call_count == 2:
            return {"success": True, "observation": BrowserObservation(observation_id="2", url="", title="", elements=[], media_elements=[MediaElement(tag="video", src="vid", paused=False, current_time=0.0, duration=10.0, ended=False, ready_state=4, muted=False, volume=1.0)])}
        else:
            return {"success": True, "observation": BrowserObservation(observation_id="3", url="", title="", elements=[], media_elements=[MediaElement(tag="video", src="vid", paused=False, current_time=2.0, duration=10.0, ended=False, ready_state=4, muted=False, volume=1.0)])}

    call_count = 0
    with patch.object(browser_provider, '_observe', side_effect=mock_observe):
        with patch('app.tools.desktop.browser.browser_executor.browser_executor.interact', new_callable=AsyncMock) as mock_interact:
            with patch('app.tools.desktop.browser.browser_resolver.browser_resolver.resolve', new_callable=AsyncMock) as mock_resolve:
                mock_interact.return_value = {"success": True, "message": "Clicked"}
                mock_resolve.return_value = BrowserElement(id="ast-1-0", tag="button", role="button", name="Play Video")
                
                res = await browser_provider.interact("CLICK", "play video")
                assert res["success"] is True
                assert res["verified"] is True

@pytest.mark.asyncio
async def test_media_not_playing_is_not_verified():
    from app.tools.desktop.browser.browser_provider import browser_provider
    from app.tools.desktop.browser.browser_observation import BrowserObservation, BrowserElement, MediaElement
    
    async def mock_observe():
        nonlocal call_count
        call_count += 1
        return {"success": True, "observation": BrowserObservation(observation_id=str(call_count), url="", title="", elements=[], media_elements=[MediaElement(tag="video", src="vid", paused=True, current_time=0.0, duration=10.0, ended=False, ready_state=4, muted=False, volume=1.0)])}

    call_count = 0
    with patch.object(browser_provider, '_observe', side_effect=mock_observe):
        with patch('app.tools.desktop.browser.browser_executor.browser_executor.interact', new_callable=AsyncMock) as mock_interact:
            with patch('app.tools.desktop.browser.browser_resolver.browser_resolver.resolve', new_callable=AsyncMock) as mock_resolve:
                mock_interact.return_value = {"success": True, "message": "Clicked"}
                mock_resolve.return_value = BrowserElement(id="ast-1-0", tag="button", role="button", name="Play Video")
                
                res = await browser_provider.interact("CLICK", "play video")
                assert res["success"] is False
                assert res["error"]["code"] == "PLAYBACK_NOT_CONFIRMED"

@pytest.mark.asyncio
async def test_goal_does_not_complete_without_final_verification():
    from app.ai.orchestrator.runtime import GoalRuntime
    from app.domain.goals import Goal, Task, Intent
    from app.domain.entities import Entity
    
    goal = Goal(goal_id="1", objective="Test", tasks=[Task(task_id="t1", description="desc", intents=[Intent(intent_id="i1", capability_id="browser.click", target=Entity(id="btn", name="btn", entity_type="UIElement"), parameters={})])])
    runtime = GoalRuntime(goal)
    
    with patch('app.ai.orchestrator.runtime.action_executor.execute_tool_call', new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"success": True, "verified": False}
        events = [e async for e in runtime.run()]
        
        goal_failed = any(e.event_type.name == "GOAL_FAILED" for e in events)
        assert goal_failed
