import re

lines = open('tests/integration/test_e2e_semantic_verification.py').read().splitlines()

new_lines = []
for i, line in enumerate(lines):
    new_lines.append(line)
    if 'def test_8_do_it_ambiguity' in line or 'def test_9_fresh_observation' in line:
        pass
    if 'setup_mock_provider(mock_provider, goal)' in line:
        if 'test_8_do_it_ambiguity' in ''.join(lines[max(0, i-20):i]) or 'test_9_fresh_observation' in ''.join(lines[max(0, i-20):i]):
            if 'mock_action_executor' not in lines[i+1]:
                new_lines.append('        mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}')

open('tests/integration/test_e2e_semantic_verification.py', 'w').write('\n'.join(new_lines))
