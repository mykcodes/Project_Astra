import re

c = open('tests/integration/test_e2e_semantic_verification.py').read()

new_setup_mock_provider = """
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
"""

c = re.sub(
    r"def setup_mock_provider\(mock_provider, goal, text_chunks=None\):\n    mock_provider\.generate\.return_value = AIResponse\([\s\S]*?\n    \)",
    new_setup_mock_provider.strip(),
    c
)

open('tests/integration/test_e2e_semantic_verification.py', 'w').write(c)
