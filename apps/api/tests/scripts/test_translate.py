"""Tests for LLMClient.chat() and translate_fields() (Tarea 4).

Mocking strategy (per A-a):
  Tests inject a fake openai client into LLMClient.__init__ via the
  ``client`` parameter. No monkeypatching of openai.OpenAI at module level.
  All LLM interactions are deterministic.

Retry policy (per C-a):
  Transient: APIConnectionError, RateLimitError, APITimeoutError → retry
  with exponential backoff (1s, 2s, 4s, up to max_retries=3 by default).
  Other errors: fail loud without retry.

Output format (per B-b):
  translate_fields expects LLM to return a JSON object (with same keys as
  input). Handles raw JSON and ```json code fences. Falls back to original
  fields if response is malformed or LLM fails.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import openai
import pytest

from backend.rag.llm_client import LLMClient, StreamError
from scripts.ingest_repo import translate_fields


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

class FakeChatCompletions:
    """Stand-in for openai.OpenAI().chat.completions.

    Tracks all calls and lets you script side effects (a list of return
    values or exceptions to raise on each successive call).
    """

    def __init__(self, *, return_value=None, side_effect=None) -> None:
        self.return_value = return_value
        self.side_effect = side_effect
        self.call_count = 0
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.call_count += 1
        self.calls.append(kwargs)
        if self.side_effect is not None:
            if isinstance(self.side_effect, list):
                idx = min(self.call_count - 1, len(self.side_effect) - 1)
                item = self.side_effect[idx]
                if isinstance(item, BaseException):
                    raise item
                return item
            elif isinstance(self.side_effect, BaseException):
                raise self.side_effect
        if self.return_value is not None:
            return self.return_value
        raise AssertionError("FakeChatCompletions: no return_value configured")


def _success_response(content: str = "ok") -> MagicMock:
    """Build a fake chat completion response."""
    message = MagicMock()
    message.content = content
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _build_llm(completions: FakeChatCompletions) -> LLMClient:
    """Wire an LLMClient to a fake openai client."""
    inner = MagicMock()
    inner.chat.completions = completions
    return LLMClient(
        base_url="https://api.example.com/v1",
        api_key="test-key",
        model="test-model",
        client=inner,
    )


def _conn_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=MagicMock())


def _timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=MagicMock())


def _rate_limit_error() -> openai.RateLimitError:
    resp = MagicMock()
    resp.status_code = 429
    return openai.RateLimitError(message="rate limited", response=resp, body=None)


def _auth_error() -> openai.AuthenticationError:
    resp = MagicMock()
    resp.status_code = 401
    return openai.AuthenticationError(message="bad key", response=resp, body=None)


def _bad_request_error() -> openai.BadRequestError:
    resp = MagicMock()
    resp.status_code = 400
    return openai.BadRequestError(message="bad input", response=resp, body=None)


# ===========================================================================
# LLMClient.__init__ — client injection (A-a)
# ===========================================================================

class TestLLMClientConstructor:
    def test_injected_client_is_used(self):
        injected = MagicMock()
        injected.chat.completions = FakeChatCompletions(
            return_value=_success_response("hi")
        )
        client = LLMClient(
            base_url="x", api_key="y", model="z", client=injected
        )
        assert client._client is injected

    def test_no_client_constructs_openai_default(self):
        from unittest.mock import patch
        with patch("openai.OpenAI") as mock_cls:
            mock_cls.return_value = MagicMock()
            LLMClient(base_url="x", api_key="y", model="z")
            mock_cls.assert_called_once_with(base_url="x", api_key="y")

    def test_existing_streaming_path_still_works_with_injected_client(self):
        injected = MagicMock()
        injected.chat.completions.create.return_value = iter([
            MagicMock(choices=[MagicMock(delta=MagicMock(content="a"))]),
            MagicMock(choices=[MagicMock(delta=MagicMock(content="b"))]),
        ])
        client = LLMClient(
            base_url="x", api_key="y", model="z", client=injected
        )
        assert list(client.stream_chat("sys", "usr")) == ["a", "b"]


# ===========================================================================
# LLMClient.chat() — happy path
# ===========================================================================

class TestLLMClientChatHappyPath:
    def test_returns_content_on_success(self):
        completions = FakeChatCompletions(
            return_value=_success_response("translated text")
        )
        client = _build_llm(completions)
        assert client.chat("sys", "usr") == "translated text"

    def test_passes_model_messages_and_temperature(self):
        completions = FakeChatCompletions(return_value=_success_response("ok"))
        client = _build_llm(completions)
        client.chat("sys prompt", "usr prompt", temperature=0.3)
        call = completions.calls[0]
        assert call["model"] == "test-model"
        assert call["messages"] == [
            {"role": "system", "content": "sys prompt"},
            {"role": "user", "content": "usr prompt"},
        ]
        assert call["temperature"] == 0.3

    def test_default_temperature_is_0_2(self):
        completions = FakeChatCompletions(return_value=_success_response("ok"))
        client = _build_llm(completions)
        client.chat("sys", "usr")
        assert completions.calls[0]["temperature"] == 0.2

    def test_empty_content_raises_stream_error(self):
        completions = FakeChatCompletions(
            return_value=_success_response(None)
        )
        client = _build_llm(completions)
        with pytest.raises(StreamError, match="empty"):
            client.chat("sys", "usr")


# ===========================================================================
# LLMClient.chat() — retry policy (C-a)
# ===========================================================================

class TestLLMClientChatRetries:
    def test_retries_on_connection_error_then_succeeds(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        completions = FakeChatCompletions(side_effect=[
            _conn_error(),
            _success_response("finally"),
        ])
        client = _build_llm(completions)
        assert client.chat("sys", "usr") == "finally"
        assert completions.call_count == 2
        assert sleeps == [1]

    def test_retries_on_rate_limit(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        completions = FakeChatCompletions(side_effect=[
            _rate_limit_error(),
            _success_response("ok"),
        ])
        client = _build_llm(completions)
        assert client.chat("sys", "usr") == "ok"
        assert completions.call_count == 2

    def test_retries_on_timeout(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        completions = FakeChatCompletions(side_effect=[
            _timeout_error(),
            _success_response("ok"),
        ])
        client = _build_llm(completions)
        assert client.chat("sys", "usr") == "ok"
        assert completions.call_count == 2

    def test_exponential_backoff_1_2_4(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        completions = FakeChatCompletions(side_effect=[
            _conn_error(),
            _conn_error(),
            _conn_error(),
            _success_response("ok"),
        ])
        client = _build_llm(completions)
        client.chat("sys", "usr")
        assert sleeps == [1, 2, 4]
        assert completions.call_count == 4

    def test_exhausted_retries_raises_stream_error(self, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        completions = FakeChatCompletions(side_effect=[
            _conn_error(),
            _conn_error(),
            _conn_error(),
            _conn_error(),
        ])
        client = _build_llm(completions)
        with pytest.raises(StreamError, match="4 attempts"):
            client.chat("sys", "usr")
        # max_retries=3 → 1 initial + 3 retries = 4 attempts total
        assert completions.call_count == 4

    def test_max_retries_zero_no_retries(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        completions = FakeChatCompletions(side_effect=[_conn_error()])
        client = _build_llm(completions)
        with pytest.raises(StreamError):
            client.chat("sys", "usr", max_retries=0)
        assert completions.call_count == 1
        assert sleeps == []


# ===========================================================================
# LLMClient.chat() — non-retryable errors
# ===========================================================================

class TestLLMClientChatNonRetryable:
    def test_authentication_error_fails_loud_without_retry(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        completions = FakeChatCompletions(side_effect=[_auth_error()])
        client = _build_llm(completions)
        with pytest.raises(StreamError, match="AuthenticationError"):
            client.chat("sys", "usr")
        assert completions.call_count == 1
        assert sleeps == []

    def test_bad_request_fails_loud_without_retry(self, monkeypatch):
        sleeps: list[float] = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))
        completions = FakeChatCompletions(side_effect=[_bad_request_error()])
        client = _build_llm(completions)
        with pytest.raises(StreamError):
            client.chat("sys", "usr")
        assert completions.call_count == 1
        assert sleeps == []


# ===========================================================================
# translate_fields — happy path (B-b JSON)
# ===========================================================================

class TestTranslateFieldsHappy:
    def test_es_to_en_translates(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": "Real-Time Data Pipeline", '
            '"summary": "Pipeline for processing data in real time."}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {
                "title": "Pipeline de datos en tiempo real",
                "summary": "Pipeline para procesar datos en tiempo real.",
            },
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Real-Time Data Pipeline"
        assert result["summary"] == "Pipeline for processing data in real time."

    def test_en_to_es_translates(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": "Pipeline de datos en tiempo real"}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Real-Time Data Pipeline"},
            source_lang="en", target_lang="es", llm=client,
        )
        assert result["title"] == "Pipeline de datos en tiempo real"

    def test_handles_json_in_code_fence(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '```json\n{"title": "Translated"}\n```'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Translated"

    def test_handles_bare_code_fence(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '```\n{"title": "Translated"}\n```'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Translated"

    def test_preamble_text_then_json(self):
        completions = FakeChatCompletions(return_value=_success_response(
            'Here is the translation:\n{"title": "Translated"}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Translated"

    def test_temperature_low_for_translation(self):
        completions = FakeChatCompletions(
            return_value=_success_response('{"x": "y"}')
        )
        client = _build_llm(completions)
        translate_fields(
            {"x": "y"}, source_lang="es", target_lang="en", llm=client
        )
        assert completions.calls[0]["temperature"] == 0.2

    def test_system_prompt_instructs_to_preserve_proper_names(self):
        completions = FakeChatCompletions(
            return_value=_success_response('{"x": "y"}')
        )
        client = _build_llm(completions)
        translate_fields(
            {"x": "y"}, source_lang="es", target_lang="en", llm=client
        )
        sys_msg = completions.calls[0]["messages"][0]["content"].lower()
        assert "proper name" in sys_msg or "technical term" in sys_msg

    def test_user_message_contains_input_fields(self):
        completions = FakeChatCompletions(
            return_value=_success_response('{"name": "X"}')
        )
        client = _build_llm(completions)
        translate_fields(
            {"name": "HiRag15k"},
            source_lang="en", target_lang="es", llm=client,
        )
        user_msg = completions.calls[0]["messages"][1]["content"]
        assert "HiRag15k" in user_msg


# ===========================================================================
# translate_fields — fallback to original (T4.4)
# ===========================================================================

class TestTranslateFieldsFallback:
    def test_llm_exhausted_retries_returns_original(self):
        completions = FakeChatCompletions(side_effect=[
            _conn_error(),
            _conn_error(),
            _conn_error(),
            _conn_error(),
        ])
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result == {"title": "Original"}

    def test_malformed_json_returns_original(self):
        completions = FakeChatCompletions(return_value=_success_response(
            "This is not JSON at all"
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result == {"title": "Original"}

    def test_missing_keys_fall_back_per_key(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": "Translated"}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original Title", "summary": "Original Summary"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Translated"
        assert result["summary"] == "Original Summary"

    def test_extra_keys_in_response_ignored(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": "Translated", "summary": "T-summary", "extra": "ignored"}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original", "summary": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert "extra" not in result
        assert result == {"title": "Translated", "summary": "T-summary"}

    def test_non_string_value_falls_back_for_that_key(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": 12345, "summary": "Translated"}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original", "summary": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Original"
        assert result["summary"] == "Translated"

    def test_empty_string_value_falls_back(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": "", "summary": "Translated"}'
        ))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original", "summary": "Original"},
            source_lang="es", target_lang="en", llm=client,
        )
        assert result["title"] == "Original"
        assert result["summary"] == "Translated"


# ===========================================================================
# translate_fields — input validation
# ===========================================================================

class TestTranslateFieldsValidation:
    def test_same_source_and_target_returns_copy_without_calling_llm(self):
        completions = FakeChatCompletions(return_value=_success_response(""))
        client = _build_llm(completions)
        result = translate_fields(
            {"title": "Original"},
            source_lang="es", target_lang="es", llm=client,
        )
        assert result == {"title": "Original"}
        assert completions.call_count == 0

    def test_empty_fields_returns_empty_without_calling_llm(self):
        completions = FakeChatCompletions(return_value=_success_response(""))
        client = _build_llm(completions)
        result = translate_fields({}, "es", "en", llm=client)
        assert result == {}
        assert completions.call_count == 0

    def test_invalid_source_lang_raises(self):
        completions = FakeChatCompletions(return_value=_success_response(""))
        client = _build_llm(completions)
        with pytest.raises(ValueError, match="only es/en"):
            translate_fields(
                {"x": "y"}, source_lang="fr", target_lang="en", llm=client
            )

    def test_invalid_target_lang_raises(self):
        completions = FakeChatCompletions(return_value=_success_response(""))
        client = _build_llm(completions)
        with pytest.raises(ValueError, match="only es/en"):
            translate_fields(
                {"x": "y"}, source_lang="es", target_lang="de", llm=client
            )

    def test_input_dict_not_mutated(self):
        completions = FakeChatCompletions(return_value=_success_response(
            '{"title": "Translated", "summary": "T-summary"}'
        ))
        client = _build_llm(completions)
        original = {"title": "Original", "summary": "Original"}
        snapshot = dict(original)
        translate_fields(original, "es", "en", llm=client)
        assert original == snapshot
