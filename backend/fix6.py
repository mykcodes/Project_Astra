import re

lines = open('tests/integration/test_e2e_semantic_verification.py').read().splitlines()

# Ensure we modify events checking for test_10, 11, 12, and fix 8, 9 missing return_value
for i, line in enumerate(lines):
    if 'goal_completed_event = next((e for e in events if isinstance(e, ExecutionEventType) and e == ExecutionEventType.GOAL_COMPLETED), None)' in line:
        lines[i] = '        events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]\n        goal_completed_event = next((e for e in events_json if e.get("type") == "GOAL_COMPLETED"), None)'
    if 'goal_failed_event = next((e for e in events if isinstance(e, ExecutionEventType) and e == ExecutionEventType.GOAL_FAILED), None)' in line:
        lines[i] = '        goal_failed_event = next((e for e in events_json if e.get("type") == "GOAL_FAILED"), None)'
    if 'goal_failed_event = next((e for e in events if getattr(e, \'event_type\', None) == ExecutionEventType.GOAL_FAILED), None)' in line:
        lines[i] = '        events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]\n        goal_failed_event = next((e for e in events_json if e.get("type") == "GOAL_FAILED"), None)'
        
# For test 8 and 9, let's explicitly inject the return_value
import io
buf = io.StringIO()
skip = False
for line in lines:
    if 'def test_8_do_it_ambiguity(' in line or 'def test_9_fresh_observation(' in line:
        buf.write(line + "\n")
        continue
        
    if 'events = [e async for e in session.chat_stream("Do it")]' in line or 'events = [e async for e in session.chat_stream("Click")]' in line:
        buf.write('        mock_action_executor.execute_intent.return_value = {"success": True, "verified": True, "verification_result": VerificationResult(verified=True, verification_type="T", expected_state="T", actual_state="T")}\n')
        buf.write(line + "\n")
        continue
        
    buf.write(line + "\n")

open('tests/integration/test_e2e_semantic_verification.py', 'w').write(buf.getvalue())
