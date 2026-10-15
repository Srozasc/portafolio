"""OpenAI-compatible embedder using the official openai SDK.

See design.md Decision 6.
Wraps openai.OpenAI with a configurable base_url for use with
MiniMax, OpenAI, LM Studio, Ollama, or any other OpenAI-compatible API.
"""

from __future__ import annotations

import openai


class Embedder:
    """OpenAI-compatible embeddings client.

    Attributes:
        model: The embedding model name passed to the API.
    """

    def __init__(self, base_url: str, api_key: str, model: str) -> None:
        """Initialise the embedder.

        Args:
            base_url: Base URL of the OpenAI-compatible API (e.g. "https://api.openai.com/v1").
            api_key: API key for the embedding service.
            model: Model name for embeddings (e.g. "text-embedding-3-small").
        """
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Args:
            texts: List of string texts to embed.

        Returns:
            List of embedding vectors (list of floats), one per input text,
            in the same order.
        """
        response = self._client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]
