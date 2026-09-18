"""Unit tests for backend.rag.llm_client.

Per Engram #19: AsyncMock() returns a coroutine, not an async iterator.
Tests use a plain generator (sync) because openai SDK stream=True is sync.
Covers:
  (a) token delta forwarding
  (b) mid-stream error → StreamError raised (not HTTPException)
  (c) connection-failure pre-first-byte handled
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.llm_client import LLMClient, StreamError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fake_stream_tokens(*tokens: str, error_after: str | None = None):
    """Synchronous generator that yields token chunks then raises RuntimeError.

    openai SDK stream=True returns a synchronous iterator, not async.
    Use as return_value for mock.chat.completions.create.
    """
    for token in tokens:
        yield MagicMock(choices=[MagicMock(delta=MagicMock(content=token))])
    if error_after:
        raise RuntimeError(error_after)


class TestLLMClient:
    """Streaming LLM client tests (no network)."""

    def test_stream_chat_yields_tokens(self):
        """Token deltas are forwarded one by one."""
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = list(
            fake_stream_tokens("Hola", " ", "mundo")
        )
        mock_openai_cls = MagicMock(return_value=mock_instance)

        with patch("openai.OpenAI", mock_openai_cls):
            client = LLMClient(
                base_url="https://api.MiniMax.io/v1",
                api_key="test-key",
                model="MiniMax-M2.7-highspeed",
            )
            tokens = list(client.stream_chat("system prompt", "user prompt"))

        assert tokens == ["Hola", " ", "mundo"]
        mock_instance.chat.completions.create.assert_called_once_with(
            model="MiniMax-M2.7-highspeed",
            messages=[
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
            stream=True,
        )

    def test_stream_chat_mid_stream_error_raises_stream_error(self):
        """Mid-stream RuntimeError → StreamError raised (not HTTPException).

        Per Engram #19: mid-stream failures must raise StreamError, not
        HTTPException or raw RuntimeError.
        """
        mock_instance = MagicMock()
        # Create a generator that yields then raises
        def gen():
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="first"))])
            yield MagicMock(choices=[MagicMock(delta=MagicMock(content="second"))])
            raise RuntimeError("kaboom")
        mock_instance.chat.completions.create.return_value = gen()
        mock_openai_cls = MagicMock(return_value=mock_instance)

        with patch("openai.OpenAI", mock_openai_cls):
            client = LLMClient(
                base_url="https://api.MiniMax.io/v1",
                api_key="test-key",
                model="MiniMax-M2.7-highspeed",
            )

            tokens = []
            with pytest.raises(StreamError) as exc_info:
                for token in client.stream_chat("system", "user"):
                    tokens.append(token)

            # First two tokens should have been yielded
            assert tokens == ["first", "second"]
            # It's a StreamError, not RuntimeError
            assert isinstance(exc_info.value, StreamError)

    def test_connection_failure_pre_first_byte_raises_stream_error(self):
        """Connection error before first token → StreamError at invocation."""
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.side_effect = ConnectionError(
            "Connection refused"
        )
        mock_openai_cls = MagicMock(return_value=mock_instance)

        with patch("openai.OpenAI", mock_openai_cls):
            client = LLMClient(
                base_url="https://api.MiniMax.io/v1",
                api_key="test-key",
                model="MiniMax-M2.7-highspeed",
            )

            with pytest.raises(StreamError) as exc_info:
                gen = client.stream_chat("system", "user")
                next(gen)

            assert isinstance(exc_info.value, StreamError)

    def test_llm_client_stores_model(self):
        """The model attribute reflects what was passed to __init__."""
        mock_instance = MagicMock()
        mock_instance.chat.completions.create.return_value = list(
            fake_stream_tokens()
        )
        mock_openai_cls = MagicMock(return_value=mock_instance)

        with patch("openai.OpenAI", mock_openai_cls):
            client = LLMClient(
                base_url="http://localhost:1234/v1",
                api_key="not-needed",
                model="my-model",
            )
            assert client.model == "my-model"
