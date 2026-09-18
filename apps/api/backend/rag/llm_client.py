"""OpenAI-compatible streaming LLM client.

See design.md Decision 3 and Engram #19.
Wraps openai.OpenAI with a configurable base_url for streaming chat.
StreamError is raised on mid-stream failures (not HTTPException per Engram #19).
"""

from __future__ import annotations

from typing import Iterator

import openai


class StreamError(Exception):
    """Raised when the LLM stream fails mid-stream.

    Per Engram #19: mid-stream failures must raise StreamError (not
    HTTPException) so they can be caught at a higher level and surfaced
    as SSE error events without crashing the streaming generator.

    IMPORTANT: the message of this exception will be surfaced to the HTTP
    client via the SSE error event in Phase 3. Do NOT interpolate raw SDK
    exception text, stack traces, request bodies, response fragments, or
    model URLs into the message — use ``type(exc).__name__`` or a
    constant string. The original SDK exception is preserved on
    ``__cause__`` for server-side logging.
    """


class LLMClient:
    """OpenAI-compatible streaming chat client."""

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        """Initialise the LLM client.

        Args:
            base_url: Base URL of the OpenAI-compatible API
                      (e.g. "https://api.MiniMax.io/v1").
            api_key: API key for the LLM service.
            model: Chat model name (e.g. "MiniMax-M2.7-highspeed").
        """
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)
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
