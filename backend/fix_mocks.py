import re

with open("tests/integration/test_e2e_semantic_verification.py") as f:
    text = f.read()

text = text.replace('arguments={"goal_plan":', 'arguments={"goal":')

# Add imports
if "AIResponse" not in text:
    text = text.replace("from app.ai.providers.types import ToolCall, ToolResult", 
                        "from app.ai.providers.types import ToolCall, ToolResult, AIResponse, TokenUsage, AIResponseChunk")

# Add setup helper
setup_helper = """
def setup_mock_provider(mock_provider, goal, text_chunks=None):
    mock_provider.generate.return_value = AIResponse(
        content="", model="test", provider="test", usage=TokenUsage(0,0,0), finish_reason="stop",
        tool_calls=[build_mock_tool_call(goal)] if goal else []
    )
    
    async def _gen(*a, **kw):
        for chunk in (text_chunks or []):
            yield AIResponseChunk(content=chunk, finish_reason=None)
        yield AIResponseChunk(content="", finish_reason="stop")
        
    mock_provider.generate_stream.side_effect = _gen
"""
text = text.replace('def mock_async_gen(lst):\n    async def _gen(*a, **kw):\n        for i in lst:\n            yield i\n    return _gen\n\n', setup_helper)

# Replace instances
# One liners: mock_provider.generate_stream = mock_async_gen([{"type": "tool_call", "tool_call": build_mock_tool_call(goal)}])
text = re.sub(r'mock_provider\.generate_stream = mock_async_gen\(\[\{"type": "tool_call", "tool_call": build_mock_tool_call\((.*?)\)\}\]\)', r'setup_mock_provider(mock_provider, \1)', text)

# Multiliners with text:
def repl_multi(m):
    goal_name = m.group(1)
    content = m.group(2)
    return f'setup_mock_provider(mock_provider, {goal_name}, ["{content}"])'

text = re.sub(r'mock_provider\.generate_stream = mock_async_gen\(\[\s*\{"type": "tool_call", "tool_call": build_mock_tool_call\((.*?)\)\},\s*\{"type": "text", "content": "(.*?)"\}\s*\]\)', repl_multi, text)

with open("tests/integration/test_e2e_semantic_verification.py", "w") as f:
    f.write(text)
