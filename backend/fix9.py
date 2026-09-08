with open('tests/integration/test_e2e_semantic_verification.py', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.strip().startswith('goal_completed_event = next((e for e in events_json'):
        # Ensure it has exactly 8 spaces
        new_lines.append('        ' + line.strip() + '\n')
    elif line.strip().startswith('goal_failed_event = next((e for e in events_json'):
        # Ensure exactly 8 spaces
        new_lines.append('        ' + line.strip() + '\n')
    elif line.strip().startswith('events_json = [json.loads(e.replace('):
        new_lines.append('        ' + line.strip() + '\n')
    else:
        new_lines.append(line)

with open('tests/integration/test_e2e_semantic_verification.py', 'w') as f:
    f.writelines(new_lines)
