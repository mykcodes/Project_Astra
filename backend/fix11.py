import json

with open('tests/integration/test_e2e_semantic_verification.py', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if 'events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]' in line:
        new_lines.append(line.replace('events_json = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e]', 'events_json = [json.loads(e) for e in events if "{" in e]'))
    elif 'text_blocks = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e and json.loads(e.replace("data: ", "")).get("type") == "ASSISTANT_RESPONSE"]' in line:
        new_lines.append(line.replace('text_blocks = [json.loads(e.replace("data: ", "")) for e in events if "data: " in e and json.loads(e.replace("data: ", "")).get("type") == "ASSISTANT_RESPONSE"]', 'text_blocks = [json.loads(e) for e in events if "{" in e and json.loads(e).get("event_type") == "ASSISTANT_RESPONSE"]'))
    elif 'e.get("type")' in line:
        new_lines.append(line.replace('e.get("type")', 'e.get("event_type")'))
    else:
        new_lines.append(line)

with open('tests/integration/test_e2e_semantic_verification.py', 'w') as f:
    f.writelines(new_lines)
