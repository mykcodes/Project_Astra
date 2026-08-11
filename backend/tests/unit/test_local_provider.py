import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from app.ai.providers.local.provider import LocalProvider
from app.ai.providers.types import AIRequest, AIMessage, MessageRole
from app.ai.providers.errors import ProviderConfigurationError, ProviderUnavailableError
from app.ai.providers.manager import ProviderManager


@pytest.fixture
def mock_settings():
    with patch("app.ai.providers.local.provider.get_settings") as mock:
        settings = MagicMock()
        settings.astra_local_enabled = True
        settings.astra_local_runtime = "openai"
        settings.astra_local_model = "llama-3-8b-instruct"
        settings.astra_local_base_url = "http://localhost:1234/v1"
        settings.astra_local_context_length = 2048
        settings.astra_local_max_tokens = 1024
        settings.astra_local_temperature = 0.7
        mock.return_value = settings
        yield settings


@pytest.mark.asyncio
async def test_local_provider_initialization_disabled():
    with patch("app.ai.providers.local.provider.get_settings") as mock:
        settings = MagicMock()
        settings.astra_local_enabled = False
        mock.return_value = settings
        with pytest.raises(ProviderConfigurationError) as exc:
            LocalProvider()
        assert "Local AI Provider is disabled" in str(exc.value)


@pytest.mark.asyncio
async def test_local_provider_initialization_enabled(mock_settings):
    provider = LocalProvider()
    assert provider.provider_name == "local"
    assert provider.default_model == "llama-3-8b-instruct"
    await provider.close()


@pytest.mark.asyncio
async def test_local_runtime_unavailable():
    with patch("app.ai.providers.local.provider.get_settings") as mock:
        settings = MagicMock()
        settings.astra_local_enabled = True
        settings.astra_local_runtime = "openai"
        settings.astra_local_model = "" # Force discovery
        settings.astra_local_base_url = "http://localhost:1234/v1"
        mock.return_value = settings
        
        provider = LocalProvider()
        
        with patch.object(provider.runtime.client, "get", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection refused", request=MagicMock())
            
            with pytest.raises(ProviderUnavailableError):
                await provider._resolve_model()
        await provider.close()


@pytest.mark.asyncio
async def test_successful_local_generation(mock_settings):
    provider = LocalProvider()
    request = AIRequest(messages=[AIMessage(role=MessageRole.USER, content="Hello")])
    
    with patch.object(provider.runtime.client, "post", new_callable=AsyncMock) as mock_post:
        
        mock_response_post = MagicMock()
        mock_response_post.json.return_value = {
            "choices": [{"message": {"content": "Hi there"}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 10}
        }
        mock_response_post.raise_for_status.return_value = None
        mock_post.return_value = mock_response_post
        
        response = await provider.generate(request)
        assert response.content == "Hi there"
        assert response.model == "llama-3-8b-instruct" # Skips discovery due to default_model configured
        assert response.provider == "local"
        
    await provider.close()


@pytest.mark.asyncio
async def test_provider_manager_fallback_to_local(mock_settings):
    with patch("app.ai.providers.manager.get_settings") as mock_mgr_settings:
        mgr_settings = MagicMock()
        mgr_settings.astra_ai_provider = "groq"
        mgr_settings.astra_ai_fallback_providers = "local"
        mgr_settings.astra_provider_cooldown_seconds = 60
        mgr_settings.astra_local_enabled = True
        mgr_settings.astra_local_runtime = "openai"
        mgr_settings.astra_local_model = "llama-3-8b-instruct"
        mgr_settings.astra_local_base_url = "http://localhost:1234/v1"
        mgr_settings.astra_local_context_length = 2048
        mgr_settings.astra_local_max_tokens = 1024
        mgr_settings.astra_local_temperature = 0.7
        mock_mgr_settings.return_value = mgr_settings
        
        manager = ProviderManager()
        assert manager.configured_order == ["groq", "local"]
        
        # Mock Groq to fail with ProviderUnavailableError
        groq_provider = manager.providers["groq"]
        groq_provider.generate = AsyncMock(side_effect=ProviderUnavailableError("Groq Down"))
        
        # Mock Local to succeed
        local_provider = manager.providers["local"]
        mock_response = MagicMock(content="Local Answer", provider="local")
        local_provider.generate = AsyncMock(return_value=mock_response)
        
        request = AIRequest(messages=[AIMessage(role=MessageRole.USER, content="Test")])
        response = await manager.generate(request)
        
        assert response.content == "Local Answer"
        assert response.provider == "local"
        assert not manager.health_state["groq"].available
        
    await manager.close()


@pytest.mark.asyncio
async def test_successful_local_generation_stream(mock_settings):
    provider = LocalProvider()
    request = AIRequest(messages=[AIMessage(role=MessageRole.USER, content="Hello")])
    
    # Mock httpx response stream
    mock_response = AsyncMock()
    mock_response.raise_for_status.return_value = None
    
    # Mock aiter_lines to yield SSE lines
    async def mock_aiter_lines():
        yield 'data: {"choices": [{"delta": {"content": "Hello"}}]}'
        yield 'data: {"choices": [{"delta": {"content": " World"}}]}'
        yield 'data: [DONE]'
    
    mock_response.aiter_lines = mock_aiter_lines
    
    # Mock stream context manager
    class MockStreamContextManager:
        async def __aenter__(self):
            return mock_response
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
            
    with patch.object(provider.runtime.client, "stream", return_value=MockStreamContextManager()):
        chunks = []
        async for chunk in provider.generate_stream(request):
            chunks.append(chunk)
            
        assert len(chunks) == 3
        assert chunks[0].content == "Hello"
        assert chunks[1].content == " World"
        assert chunks[2].is_done is True
        
    await provider.close()


@pytest.mark.asyncio
async def test_manager_fallback_stream(mock_settings):
    with patch("app.ai.providers.manager.get_settings") as mock_mgr_settings:
        mgr_settings = MagicMock()
        mgr_settings.astra_ai_provider = "groq"
        mgr_settings.astra_ai_fallback_providers = "local"
        mgr_settings.astra_provider_cooldown_seconds = 60
        mgr_settings.astra_local_enabled = True
        mgr_settings.astra_local_runtime = "openai"
        mgr_settings.astra_local_model = "llama-3-8b-instruct"
        mgr_settings.astra_local_base_url = "http://localhost:1234/v1"
        mgr_settings.astra_local_context_length = 2048
        mgr_settings.astra_local_max_tokens = 1024
        mgr_settings.astra_local_temperature = 0.7
        mock_mgr_settings.return_value = mgr_settings
        
        manager = ProviderManager()
        
        groq_provider = manager.providers["groq"]
        
        # Simulate Groq failing before yielding chunks
        async def groq_fail_stream(*args, **kwargs):
            raise ProviderUnavailableError("Groq Stream Down")
            yield  # To make it a generator
            
        groq_provider.generate_stream = groq_fail_stream
        
        local_provider = manager.providers["local"]
        
        async def local_success_stream(*args, **kwargs):
            yield MagicMock(content="Local", is_done=False)
            yield MagicMock(content=" Stream", is_done=False)
            
        local_provider.generate_stream = local_success_stream
        
        request = AIRequest(messages=[AIMessage(role=MessageRole.USER, content="Test")])
        chunks = []
        async for chunk in manager.generate_stream(request):
            chunks.append(chunk.content)
            
        assert "".join(chunks) == "Local Stream"
        assert not manager.health_state["groq"].available
        
    await manager.close()
