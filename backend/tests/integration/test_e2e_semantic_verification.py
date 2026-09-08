
def setup_mock_provider(mock_provider, goal, text_chunks=None):
    mock_provider.generate.return_value = AIResponse(
        content="".join(text_chunks) if text_chunks else "", model="test", provider="test", usage=TokenUsage(0,0,0), finish_reason="stop",
        tool_calls=[build_mock_tool_call(goal)] if goal else []
    )
    if text_chunks:
        async def _stream(*args, **kwargs):
            for t in text_chunks:
                yield AIResponseChunk(content=t, is_done=False, usage=TokenUsage(0,0,0))
            yield AIResponseChunk(content="", is_done=True, usage=TokenUsage(0,0,0))
        mock_provider.generate_stream.side_effect = _stream
    
    async def _gen(*a, **kw):
        for chunk in (text_chunks or []):
            yield AIResponseChunk(content=chunk, is_done=False)
        yield AIResponseChunk(content="", is_done=True)
        
    mock_provider.generate_stream = MagicMock(side_effect=_gen)
import pytest
import asyncio
import json
from unittest.mock import AsyncMock, patch, MagicMock

from app.domain.goals import Goal, Task, Intent, SemanticAction, TargetType, TargetOrdinal, TaskState, GoalState, VerificationResult
from app.ai.orchestrator.session import ConversationSession
from app.ai.providers.types import ToolCall, ToolResult, AIResponse, TokenUsage, AIResponseChunk
from app.domain.events import ExecutionEventType
from app.tools.desktop.browser.browser_observation import BrowserObservation

@pytest.fixture
def mock_provider():
    provider = AsyncMock()
    return provider

@pytest.fixture
def mock_action_executor():
    with patch('app.ai.orchestrator.runtime.action_executor') as mock_executor:
        mock_executor.execute_intent = AsyncMock()
        yield mock_executor

@pytest.fixture
def mock_browser_provider():
    with patch('app.tools.desktop.browser.browser_provider.browser_provider') as mock_browser:
        mock_browser.observe = AsyncMock(return_value={"success": True, "observation": BrowserObservation(observation_id="obs_1", url="test.com", title="Test", page_id="p1")})
        mock_browser.check_challenges = AsyncMock(return_value={"success": True})
        mock_browser.ensure_browser_session = AsyncMock()
        yield mock_browser

def build_mock_tool_call(goal: Goal) -> ToolCall:
    return ToolCall(
        id="call_1",
        name="submit_goal_plan",
        arguments={"goal": goal.model_dump()}
    )

@pytest.mark.asyncio
async def test_1_compound_command(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    # Mock LLM returning 2 sequential tasks
    goal = Goal(
        goal_id="g1",
        objective="Open Chrome and navigate to YouTube",
        tasks=[
            Task(task_id="t1", description="Open Chrome", intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open", target="Chrome")]),
            Task(task_id="t2", description="Navigate YouTube", intents=[Intent(intent_id="i2", action=SemanticAction.NAVIGATE, capability_id="browser.navigate", target="youtube.com")])
        ]
    )
    setup_mock_provider(mock_provider, goal, ["Done"])
    
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
    events = []
    async for event in session.chat_stream("Open Chrome and navigate to YouTube"):
        events.append(event)
        
    assert mock_action_executor.execute_intent.call_count == 2
    calls = mock_action_executor.execute_intent.call_args_list
    assert calls[0][0][0].action == SemanticAction.OPEN
    assert calls[1][0][0].action == SemanticAction.NAVIGATE

@pytest.mark.asyncio
async def test_2_search_play_decomposition(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    goal = Goal(
        goal_id="g2",
        objective="Open YouTube, search for Baby and play it",
        tasks=[
            Task(task_id="t1", description="Navigate YouTube", intents=[Intent(intent_id="i1", action=SemanticAction.NAVIGATE, capability_id="browser.navigate", target="youtube.com")]),
            Task(task_id="t2", description="Search Baby", intents=[Intent(intent_id="i2", action=SemanticAction.SEARCH, capability_id="browser.search", target="Baby")]),
            Task(task_id="t3", description="Play first", intents=[Intent(intent_id="i3", action=SemanticAction.PLAY, capability_id="browser.click", target_type=TargetType.SEARCH_RESULT, ordinal=TargetOrdinal.FIRST)])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    mock_browser_provider.observe.return_value = {"success": True, "observation": BrowserObservation(observation_id="obs_1", url="youtube.com/results", title="Baby", page_id="p1")}
    
    events = [e async for e in session.chat_stream("Open YouTube, search for Baby and play it")]
    
    assert mock_action_executor.execute_intent.call_count == 3
    calls = mock_action_executor.execute_intent.call_args_list
    assert calls[0][0][0].action == SemanticAction.NAVIGATE
    assert calls[1][0][0].action == SemanticAction.SEARCH
    assert calls[2][0][0].action == SemanticAction.PLAY

@pytest.mark.asyncio
async def test_3_cross_turn_context(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    # Turn 1
    goal1 = Goal(
        goal_id="g1",
        objective="Search for Baby",
        tasks=[
            Task(task_id="t1", description="Search", intents=[Intent(intent_id="i1", action=SemanticAction.SEARCH, capability_id="browser.search", target="Baby")])
        ]
    )
    setup_mock_provider(mock_provider, goal1)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T"), "browser_identity": "chrome"}
    mock_browser_provider.observe.return_value = {"success": True, "observation": BrowserObservation(observation_id="obs_1", url="youtube.com/results", title="Baby", page_id="p1")}
    
    async for e in session.chat_stream("Search for Baby"): pass
    
    assert session.execution_context.active_browser_identity == "chrome"
    assert session.execution_context.current_url == "youtube.com/results"
    
    # Turn 2
    goal2 = Goal(
        goal_id="g2",
        objective="Play the first video",
        tasks=[
            Task(task_id="t2", description="Play", intents=[Intent(intent_id="i2", action=SemanticAction.PLAY, capability_id="browser.click", target_type=TargetType.SEARCH_RESULT, ordinal=TargetOrdinal.FIRST)])
        ]
    )
    setup_mock_provider(mock_provider, goal2)
    
    async for e in session.chat_stream("Play the first video"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    assert len(calls) == 2
    turn2_intent = calls[1][0][0]
    turn2_args = calls[1][0][1]
    
    assert turn2_args.get("browser_name") == "chrome"
    assert turn2_args.get("_current_url") == "youtube.com/results"

@pytest.mark.asyncio
async def test_5_pronoun(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    # Setup Context
    session.execution_context.last_intent = Intent(intent_id="i1", action=SemanticAction.SEARCH, capability_id="browser.search", target="Baby")
    
    goal = Goal(
        goal_id="g1",
        objective="Play it",
        tasks=[
            Task(task_id="t1", description="Play it", intents=[Intent(intent_id="i2", action=SemanticAction.PLAY, capability_id="browser.click", target="it")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
    async for e in session.chat_stream("Play it"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    compiled_intent = calls[0][0][0]
    assert compiled_intent.target == "Baby"

@pytest.mark.asyncio
async def test_6_repeat(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    session.execution_context.last_intent = Intent(intent_id="i1", action=SemanticAction.SEARCH, capability_id="browser.search", target="Baby")
    
    goal = Goal(
        goal_id="g1",
        objective="Do it again",
        tasks=[
            Task(task_id="t1", description="Repeat", intents=[Intent(intent_id="i2", action=SemanticAction.REPEAT)])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
    async for e in session.chat_stream("Do it again"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    compiled_intent = calls[0][0][0]
    assert compiled_intent.action == SemanticAction.SEARCH
    assert compiled_intent.target == "Baby"

@pytest.mark.asyncio
async def test_10_physical_verification(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    goal = Goal(
        goal_id="g1",
        objective="Play",
        tasks=[
            Task(task_id="t1", description="Play", intents=[Intent(intent_id="i1", action=SemanticAction.PLAY, capability_id="browser.click", target="video")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    # Action succeeds but verification fails
    mock_action_executor.execute_intent.side_effect = [
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")},
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")},
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")},
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")}
        ]
    
    events = [e async for e in session.chat_stream("Play")]
    
    events_json = [json.loads(e) for e in events if "{" in e]
    goal_completed_event = next((e for e in events_json if e.get("event_type") == "GOAL_COMPLETED"), None)
    events_json = [json.loads(e) for e in events if "{" in e]
    goal_failed_event = next((e for e in events_json if e.get("event_type") == "GOAL_FAILED"), None)
    
    assert goal_failed_event is not None
    assert goal_completed_event is None

@pytest.mark.asyncio
async def test_13_final_response_bridge(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g1",
        objective="Search",
        tasks=[
            Task(task_id="t1", description="Search", intents=[Intent(intent_id="i1", action=SemanticAction.SEARCH, capability_id="browser.search", target="Baby")])
        ]
    )
    setup_mock_provider(mock_provider, goal, ["I have executed the search."])
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
    async def _mock_generate_stream(*args, **kwargs):
        yield AIResponseChunk(content="I have executed the search.", is_done=False, usage=TokenUsage(0,0,0))
        yield AIResponseChunk(content="", is_done=True, usage=TokenUsage(0,0,0))
    mock_provider.generate_stream = _mock_generate_stream

    events = [e async for e in session.chat_stream("Search for baby")]
    text_blocks = [json.loads(e) for e in events if "{" in e and json.loads(e).get("event_type") == "ASSISTANT_RESPONSE"]
    assert len(text_blocks) >= 1

@pytest.mark.asyncio
async def test_14_normal_chat_regression(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    setup_mock_provider(mock_provider, None, ["Hello, how can I help?"])
    
    events = [e async for e in session.chat_stream("Hello")]
    
    assert mock_action_executor.execute_intent.call_count == 0

@pytest.mark.asyncio
async def test_4_ordinal_target(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    goal = Goal(
        goal_id="g1",
        objective="Play the first video",
        tasks=[
            Task(task_id="t1", description="Play", intents=[Intent(intent_id="i1", action=SemanticAction.PLAY, capability_id="browser.click", target_type=TargetType.SEARCH_RESULT, ordinal=TargetOrdinal.FIRST)])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
    async for e in session.chat_stream("Play the first video"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    compiled_intent = calls[0][0][0]
    assert compiled_intent.ordinal == TargetOrdinal.FIRST
    assert compiled_intent.target_type == TargetType.SEARCH_RESULT

@pytest.mark.asyncio
async def test_7_retry(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    session.execution_context.retryable_intent = Intent(intent_id="i1", action=SemanticAction.PLAY, capability_id="browser.click", target="first video")
    
    goal = Goal(
        goal_id="g1",
        objective="Retry",
        tasks=[
            Task(task_id="t1", description="Retry", intents=[Intent(intent_id="i2", action=SemanticAction.RETRY)])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
    async for e in session.chat_stream("Retry"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    compiled_intent = calls[0][0][0]
    assert compiled_intent.action == SemanticAction.PLAY
    assert compiled_intent.target == "first video"

@pytest.mark.asyncio
async def test_8_do_it_ambiguity(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g1",
        objective="Do it",
        tasks=[
            Task(task_id="t1", description="Do it", intents=[Intent(intent_id="i1", action=SemanticAction.REPEAT)])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": False, "verified": False}
    events = [e async for e in session.chat_stream("Do it")]
    events_json = [json.loads(e) for e in events if "{" in e]
    goal_failed_event = next((e for e in events_json if e.get("event_type") == "GOAL_FAILED"), None)
    assert goal_failed_event is not None

@pytest.mark.asyncio
async def test_9_fresh_observation(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    goal = Goal(
        goal_id="g1",
        objective="Click",
        tasks=[
            Task(task_id="t1", description="Click", intents=[Intent(intent_id="i1", action=SemanticAction.CLICK, capability_id="browser.click", target="button")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    mock_browser_provider.observe.return_value = {"success": True, "observation": BrowserObservation(observation_id="obs_9", url="new.com", title="Title", page_id="p1")}
    
    async for e in session.chat_stream("Click"): pass
    
    # Observe is called before executing the intent
    assert mock_browser_provider.observe.call_count >= 1

@pytest.mark.asyncio
async def test_11_navigation_verification(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    goal = Goal(
        goal_id="g1",
        objective="Navigate",
        tasks=[
            Task(task_id="t1", description="Navigate", intents=[Intent(intent_id="i1", action=SemanticAction.NAVIGATE, capability_id="browser.navigate", target="site.com")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    # Action succeeds but verification fails
    mock_action_executor.execute_intent.side_effect = [
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")},
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")},
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")},
            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")}
        ]
    
    events = [e async for e in session.chat_stream("Navigate")]
    
    events_json = [json.loads(e) for e in events if "{" in e]
    goal_failed_event = next((e for e in events_json if e.get("event_type") == "GOAL_FAILED"), None)
    assert goal_failed_event is not None

@pytest.mark.asyncio
async def test_12_goal_level_verification(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    
    goal = Goal(
        goal_id="g1",
        objective="Multi task",
        tasks=[
            Task(task_id="t1", description="T1", intents=[Intent(intent_id="i1", action=SemanticAction.CONTINUE, capability_id="browser.status", parameters={})]),
            Task(task_id="t2", description="T2", intents=[Intent(intent_id="i2", action=SemanticAction.CONTINUE, capability_id="browser.status", parameters={})]),
            Task(task_id="t3", description="T3", intents=[Intent(intent_id="i3", action=SemanticAction.CONTINUE, capability_id="browser.status", parameters={})])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    # Tasks 1 & 2 succeed
    # Provide enough side effects for potential retries
    mock_action_executor.execute_intent.side_effect = [
        {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")},
        {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")},
        {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="T", expected_state="T", actual_state="T")},
        {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="T", expected_state="T", actual_state="T")},
        {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="T", expected_state="T", actual_state="T")},
        {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="T", expected_state="T", actual_state="T")}
    ]
    
    events = [e async for e in session.chat_stream("Multi")]
    
    events_json = [json.loads(e) for e in events if "{" in e]
    goal_failed_event = next((e for e in events_json if e.get("event_type") == "GOAL_FAILED"), None)
    assert goal_failed_event is not None






# --- PHASE 9B.3.1 ARCHITECTURAL CORRECTION TESTS ---

@pytest.mark.asyncio
async def test_a_capability_mapping():
    from app.tools.registry import registry
    from app.tools.errors import ToolNotFoundError
    assert registry.resolve_capability("desktop.open_application") == "execute_application_intent"
    assert registry.resolve_capability("desktop.focus_application") == "execute_application_intent"
    assert registry.resolve_capability("browser.navigate") == "execute_browser_intent"

@pytest.mark.asyncio
@patch('app.tools.desktop.browser.browser_identity.browser_registry.resolve_browser')
async def test_b_open_chrome_no_browser_session(mock_resolve_browser, mock_provider, mock_action_executor, mock_browser_provider):
    from app.tools.desktop.browser.browser_identity import BrowserIdentity
    mock_resolve_browser.return_value = BrowserIdentity(
        browser_id="b1",
        canonical_name="chrome",
        display_name="Google Chrome",
        executable_path="/path/to/chrome"
    )
    
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g_test_b",
        objective="Open Chrome",
        tasks=[
            Task(task_id="t1", description="Open Chrome", intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application", target="Chrome")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    mock_action_executor.execute_intent.return_value = {
        "success": True, 
        "verified": True, 
        "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T"),
        "diagnostics": {"canonical_name": "chrome"}
    }
    
    async for e in session.chat_stream("Open Chrome"): pass
    
    assert mock_action_executor.execute_intent.call_count == 1
    calls = mock_action_executor.execute_intent.call_args_list
    intent, tool_args = calls[0][0][0], calls[0][0][1]
    
    assert intent.capability_id == "desktop.open_application"
    assert tool_args["intent"] == "OPEN"
    assert tool_args["application"] == "Chrome"
    assert "action" not in tool_args
    
    assert session.execution_context.active_browser_identity == "chrome"
    assert mock_browser_provider.observe.call_count == 0

@pytest.mark.asyncio
async def test_c_focus_spotify(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g_test_c",
        objective="Focus Spotify",
        tasks=[
            Task(task_id="t1", description="Focus Spotify", intents=[Intent(intent_id="i1", action=SemanticAction.FOCUS, capability_id="desktop.focus_application", target="Spotify")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True}
    
    async for e in session.chat_stream("Focus Spotify"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    intent, tool_args = calls[0][0][0], calls[0][0][1]
    
    assert intent.capability_id == "desktop.focus_application"
    assert tool_args["intent"] == "FOCUS"
    assert tool_args["application"] == "Spotify"
    
    assert mock_browser_provider.observe.call_count == 0

@pytest.mark.asyncio
async def test_d_open_vs_code(mock_provider, mock_action_executor, mock_browser_provider):
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g_test_d",
        objective="Open VS Code",
        tasks=[
            Task(task_id="t1", description="Open VS Code", intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application", target="VS Code")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    mock_action_executor.execute_intent.return_value = {"success": True, "verified": True}
    
    async for e in session.chat_stream("Open VS Code"): pass
    assert mock_browser_provider.observe.call_count == 0

@pytest.mark.asyncio
@patch('app.tools.desktop.browser.browser_identity.browser_registry.resolve_browser')
async def test_e_navigate_after_browser_launch(mock_resolve_browser, mock_provider, mock_action_executor, mock_browser_provider):
    from app.tools.desktop.browser.browser_identity import BrowserIdentity
    mock_resolve_browser.return_value = BrowserIdentity(
        browser_id="b1",
        canonical_name="chrome",
        display_name="Google Chrome",
        executable_path="/path/to/chrome"
    )

    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g_test_e",
        objective="Open Chrome and navigate to YouTube",
        tasks=[
            Task(task_id="t1", description="Open Chrome", intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application", target="Chrome")]),
            Task(task_id="t2", description="Navigate YouTube", intents=[Intent(intent_id="i2", action=SemanticAction.NAVIGATE, capability_id="browser.navigate", target="youtube.com")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    mock_action_executor.execute_intent.side_effect = [
        {"success": True, "verified": True, "diagnostics": {"canonical_name": "chrome"}},
        {"success": True, "verified": True, "session_id": "session-123"}
    ]
    
    async for e in session.chat_stream("Open Chrome and navigate to YouTube"): pass
    
    calls = mock_action_executor.execute_intent.call_args_list
    assert len(calls) == 2
    
    nav_args = calls[1][0][1]
    assert nav_args.get("browser_name") == "chrome"
    assert session.execution_context.browser_session_id == "session-123"

@pytest.mark.asyncio
async def test_g_failed_goal_truthfulness(mock_provider, mock_action_executor, mock_browser_provider):
    from app.ai.providers.types import MessageRole
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g_test_g",
        objective="Open Chrome",
        tasks=[
            Task(task_id="t1", description="Open Chrome", intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application", target="Chrome")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    # Force failure for 4 attempts (1 + 3 retries)
    mock_action_executor.execute_intent.return_value = {"success": False, "error": {"code": "ToolNotFoundError", "message": "Failed to find tool"}}
    
    async for e in session.chat_stream("Open Chrome"): pass
    
    final_tool_msg = session.history[-1] # The last message should be the deterministic string
    assert final_tool_msg.role == MessageRole.ASSISTANT
    assert "Execution failed" in final_tool_msg.content

@pytest.mark.asyncio
async def test_h_waiting_goal_truthfulness(mock_provider, mock_action_executor, mock_browser_provider):
    from app.ai.providers.types import MessageRole
    session = ConversationSession(provider=mock_provider)
    goal = Goal(
        goal_id="g_test_h",
        objective="Do Something",
        tasks=[
            Task(task_id="t1", description="Do Something", intents=[Intent(intent_id="i1", action=SemanticAction.OPEN, capability_id="desktop.open_application", target="App")])
        ]
    )
    setup_mock_provider(mock_provider, goal)
    
    # Force waiting
    mock_action_executor.execute_intent.return_value = {"success": False, "error": {"code": "HUMAN_VERIFICATION_REQUIRED", "message": "Captcha detected"}}
    
    async for e in session.chat_stream("Do Something"): pass
    
    final_tool_msg = session.history[-1]
    assert final_tool_msg.role == MessageRole.ASSISTANT
    assert "Waiting for your action" in final_tool_msg.content
