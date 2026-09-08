import re

with open('tests/integration/test_e2e_semantic_verification.py', 'r') as f:
    content = f.read()

# Overwrite test 8
test_8 = '''@pytest.mark.asyncio
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
    assert goal_failed_event is not None'''

content = re.sub(r'@pytest\.mark\.asyncio\nasync def test_8_do_it_ambiguity.*?(?=@pytest\.mark\.asyncio|\Z)', test_8 + '\n\n', content, flags=re.DOTALL)

# Overwrite test 13
test_13 = '''@pytest.mark.asyncio
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
    assert len(text_blocks) >= 1'''

content = re.sub(r'@pytest\.mark\.asyncio\nasync def test_13_final_response_bridge.*?(?=@pytest\.mark\.asyncio|\Z)', test_13 + '\n\n', content, flags=re.DOTALL)

with open('tests/integration/test_e2e_semantic_verification.py', 'w') as f:
    f.write(content)
