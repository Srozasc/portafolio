"""OpenAI-compatible LLM client (streaming + non-streaming).

See design.md Decision 3 and Engram #19.
Wraps openai.OpenAI with a configurable base_url.
StreamError is raised on stream/chat failures (not HTTPException per Engram #19).
"""

from __future__ import annotations

import time
from collections.abc import Iterator

import openai


class StreamError(Exception):
    """Raised when the LLM call (streaming or non-streaming) fails.

    Per Engram #19: failures must raise StreamError (not HTTPException) so
    they can be caught at a higher level and surfaced appropriately without
    crashing upstream handlers. The message will be surfaced to clients —
    do NOT interpolate raw SDK exception text, stack traces, request
    bodies, response fragments, or model URLs into the message. Use
    ``type(exc).__name__`` or a constant string. The original SDK
    exception is preserved on ``__cause__`` for server-side logging.
    """


# Exceptions that warrant automatic retry with exponential backoff.
# Authentication and bad-request errors are NOT retried (they indicate
# config bugs that retrying won't fix).
_TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    openai.APIConnectionError,
    openai.RateLimitError,
    openai.APITimeoutError,
)


class LLMClient:
    """OpenAI-compatible chat client (streaming + non-streaming)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        client: openai.OpenAI | None = None,
    ) -> None:
        """Initialise the LLM client.

        Args:
            base_url: Base URL of the OpenAI-compatible API
                      (e.g. "https://api.MiniMax.io/v1").
            api_key: API key for the LLM service.
            model: Chat model name (e.g. "MiniMax-M2.7-highspeed").
            client: Optional pre-constructed openai.OpenAI instance. When
                    provided, ``base_url`` and ``api_key`` are ignored.
                    Used by tests to inject a mock; production code
                    passes None.
        """
        if client is None:
            client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self._client = client
        self.model = model

    def stream_chat(self, system: str, user: str) -> Iterator[str]:
        """Stream chat completion tokens.

        Yields token deltas from the LLM. On mid-stream failure,
        raises StreamError after the last successful yield.

        Args:
            system: System prompt string.
            user: User message string.

        Yields:
            Token delta strings (content from each streaming chunk).

        Raises:
            StreamError: If an error occurs during streaming after
                         at least one token has been yielded.
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        try:
            stream = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
            )
        except Exception as exc:
            # Connection failure before first byte.
            # Do NOT embed str(exc) — it can include URLs, model names, and
            # body fragments. Use the class name only; __cause__ preserves
            # the full exception for server-side logging.
            raise StreamError(f"Connection error ({type(exc).__name__})") from exc

        try:
            for chunk in stream:
                delta = chunk.choices[0].delta
                if delta and delta.content is not None:
                    yield delta.content
        except Exception as exc:
            # Mid-stream failure (e.g. server error, network drop).
            # Same sanitisation as above: only the class name in the
            # client-facing message; full exception on __cause__.
            raise StreamError(f"Mid-stream error ({type(exc).__name__})") from exc

    def chat(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.2,
        max_retries: int = 3,
    ) -> str:
        """Non-streaming chat completion.

        Retries up to ``max_retries`` times on transient errors
        (connection, rate-limit, timeout) with exponential backoff
        (1s, 2s, 4s). Auth and bad-request errors are raised
        immediately without retry.

        Args:
            system: System prompt string.
            user: User message string.
            temperature: Sampling temperature (0.0-2.0). Lower is more
                conservative; defaults to 0.2 for translation use cases.
            max_retries: Maximum number of retries after the initial
                call. Total attempts = max_retries + 1. Pass 0 to
                disable retries entirely.

        Returns:
            The LLM's response content as a string.

        Raises:
            StreamError: On empty response, exhausted retries, or any
                non-transient error (auth, bad-request, etc.).
        """
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        last_exc: BaseException | None = None
        for attempt in range(max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                )
            except _TRANSIENT_EXCEPTIONS as exc:
                last_exc = exc
                if attempt >= max_retries:
                    break
                # Exponential backoff: 1s, 2s, 4s for attempts 0, 1, 2.
                time.sleep(2 ** attempt)
                continue
            except Exception as exc:
                # Non-transient → fail loud without retry.
                # Sanitised message (class name only); full exception on __cause__.
                raise StreamError(
                    f"LLM error ({type(exc).__name__})"
                ) from exc

            # Success path: validate and return content.
            content = response.choices[0].message.content
            if content is None:
                raise StreamError("LLM returned empty content")
            return content

        # Retries exhausted.
        assert last_exc is not None  # type-guard for mypy / type checkers
        raise StreamError(
            f"LLM unavailable after {max_retries + 1} attempts "
            f"({type(last_exc).__name__})"
        ) from last_exc
