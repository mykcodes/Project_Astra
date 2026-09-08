import re

with open('tests/integration/test_e2e_semantic_verification.py', 'r') as f:
    content = f.read()

# Fix 1: mock_action_executor for test_8
replacement = '''goal_id="g1",
            objective="Do it",
            tasks=[
                Task(task_id="t1", description="Do it", intents=[Intent(intent_id="i1", action=SemanticAction.REPEAT)])
            ]
        )
        setup_mock_provider(mock_provider, goal)
        mock_action_executor.execute_intent.return_value = {"success": False, "verified": False}'''

content = re.sub(
    r'goal_id="g1",\s*objective="Do it",[\s\S]*?setup_mock_provider\(mock_provider, goal\)',
    replacement,
    content
)

# Fix 2: print events in test 13
content = re.sub(
    r'text_blocks = \[json\.loads\(e\) for e in events if "{" in e and json\.loads\(e\)\.get\("event_type"\) == "ASSISTANT_RESPONSE"\]',
    'for e in events:\n            print("EVENT:", repr(e))\n        text_blocks = [json.loads(e) for e in events if "{" in e and json.loads(e).get("event_type") == "ASSISTANT_RESPONSE"]',
    content
)

with open('tests/integration/test_e2e_semantic_verification.py', 'w') as f:
    f.write(content)
