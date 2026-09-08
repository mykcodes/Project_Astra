import re

c = open('tests/integration/test_e2e_semantic_verification.py').read()

# Add return value for test 8
c = c.replace(
    'setup_mock_provider(mock_provider, goal)\n    \n        events = [e async for e in session.chat_stream("Do it")]',
    'setup_mock_provider(mock_provider, goal)\n        mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}\n    \n        events = [e async for e in session.chat_stream("Do it")]'
)

# Add return value for test 9
c = c.replace(
    'setup_mock_provider(mock_provider, goal)\n    \n        events = [e async for e in session.chat_stream("Click")]',
    'setup_mock_provider(mock_provider, goal)\n        mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}\n    \n        events = [e async for e in session.chat_stream("Click")]'
)

# Fix side effects for test 10
c = c.replace(
    'mock_action_executor.execute_intent.return_value = {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")}',
    'mock_action_executor.execute_intent.side_effect = [\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")},\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")},\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")},\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="PLAYBACK", expected_state="PLAYING", actual_state="PAUSED")}\n        ]'
)

# Fix side effects for test 11
c = c.replace(
    'mock_action_executor.execute_intent.return_value = {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")}',
    'mock_action_executor.execute_intent.side_effect = [\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")},\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")},\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")},\n            {"success": True, "verified": False, "verification_result": VerificationResult(verified=False, verification_type="NAVIGATE", expected_state="site.com", actual_state="wrong.com")}\n        ]'
)

open('tests/integration/test_e2e_semantic_verification.py', 'w').write(c)
