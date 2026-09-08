import re
import json

with open('tests/integration/test_e2e_semantic_verification.py', 'r') as f:
    content = f.read()

# Fix 1: session.context -> session.execution_context in test_3
content = content.replace('session.context.current_url', 'session.execution_context.current_url')

# Fix 2: events parsing for test 10, 11, 12
for test in ['test_10', 'test_11', 'test_12']:
    content = re.sub(
        r'goal_failed_event = next\(\(e for e in events if.*GOAL_FAILED.*',
        'events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]\n        goal_failed_event = next((e for e in events_json if e.get("type") == "GOAL_FAILED"), None)',
        content
    )
    content = re.sub(
        r'goal_completed_event = next\(\(e for e in events if.*GOAL_COMPLETED.*',
        'events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]\n        goal_completed_event = next((e for e in events_json if e.get("type") == "GOAL_COMPLETED"), None)',
        content
    )

# Fix 3: mock_action_executor.execute_intent.return_value for test_8
if 'def test_8_do_it_ambiguity' in content:
    # Let's just manually replace test 8 body
    test_8_replacement = """    @pytest.mark.asyncio
    async def test_8_do_it_ambiguity(mock_provider, mock_action_executor, mock_browser_provider):
        session = ConversationSession(provider=mock_provider)
    
        # Empty context - no retryable intent
        goal = Goal(
            goal_id="g1",
            objective="Do it",
            tasks=[
                Task(task_id="t1", description="Do it", intents=[Intent(intent_id="i1", action=SemanticAction.REPEAT)])
            ]
        )
        setup_mock_provider(mock_provider, goal)
        mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}
    
        events = [e async for e in session.chat_stream("Do it")]
        
        events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]
        # REPEAT with no context should fail compilation or execution safely
        goal_failed_event = next((e for e in events_json if e.get("type") == "GOAL_FAILED"), None)
        assert goal_failed_event is not None
"""
    # Find test 8 start and end
    m = re.search(r'    @pytest\.mark\.asyncio\n    async def test_8_do_it_ambiguity.*?(?=    @pytest\.mark\.asyncio|\Z)', content, re.DOTALL)
    if m:
        content = content.replace(m.group(0), test_8_replacement)

# Fix 4: test 13 final response bridge
if 'def test_13_final_response_bridge' in content:
    test_13_replacement = """    @pytest.mark.asyncio
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
    
        text_blocks = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e and json.loads(e.replace("data: ", "")).get("type") == "ASSISTANT_RESPONSE"]
        assert len(text_blocks) >= 1
"""
    m = re.search(r'    @pytest\.mark\.asyncio\n    async def test_13_final_response_bridge.*?(?=    @pytest\.mark\.asyncio|\Z)', content, re.DOTALL)
    if m:
        content = content.replace(m.group(0), test_13_replacement)

with open('tests/integration/test_e2e_semantic_verification.py', 'w') as f:
    f.write(content)
