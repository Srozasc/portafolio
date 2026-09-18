"""Unit tests for backend.rag.embedder.

No network calls — openai.OpenAI SDK is mocked at the import boundary.
Verifies request shape: model kwarg and input list format.
"""

from unittest.mock import MagicMock, patch

import pytest

from backend.rag.embedder import Embedder


class TestEmbedder:
    """Embedder request shape and response parsing (no network)."""

    @patch("openai.OpenAI")
    def test_embed_single_text(self, mock_openai_cls: MagicMock):
        """One text → one embedding vector."""
        # Set up fake SDK response
        fake_embedding = [0.1, 0.2, 0.3]
        mock_instance = MagicMock()
        mock_instance.embeddings.create.return_value = MagicMock(
            data=[MagicMock(embedding=fake_embedding)]
        )
        mock_openai_cls.return_value = mock_instance

        embedder = Embedder(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="text-embedding-3-small",
        )
        result = embedder.embed(["hola mundo"])

        # Assert request shape
        mock_instance.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=["hola mundo"],
        )
        assert result == [[0.1, 0.2, 0.3]]

    @patch("openai.OpenAI")
    def test_embed_batch(self, mock_openai_cls: MagicMock):
        """Multiple texts → multiple embedding vectors, same order."""
        fake_embeddings = [
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ]
        mock_instance = MagicMock()
        mock_instance.embeddings.create.return_value = MagicMock(
            data=[
                MagicMock(embedding=fake_embeddings[0]),
                MagicMock(embedding=fake_embeddings[1]),
            ]
        )
        mock_openai_cls.return_value = mock_instance

        embedder = Embedder(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="text-embedding-nomic-embed-text-v1.5",
        )
        result = embedder.embed(["texto a", "texto b"])

        assert mock_instance.embeddings.create.call_count == 1
        call_kwargs = mock_instance.embeddings.create.call_args.kwargs
        assert call_kwargs["model"] == "text-embedding-nomic-embed-text-v1.5"
        assert call_kwargs["input"] == ["texto a", "texto b"]
        assert result == fake_embeddings

    @patch("openai.OpenAI")
    def test_embedder_stores_model(self, mock_openai_cls: MagicMock):
        """The model attribute reflects what was passed to __init__."""
        mock_instance = MagicMock()
        mock_instance.embeddings.create.return_value = MagicMock(data=[])
        mock_openai_cls.return_value = mock_instance

        embedder = Embedder(
            base_url="http://localhost:1234/v1",
            api_key="not-needed",
            model="my-embedding-model",
        )
        assert embedder.model == "my-embedding-model"

    @patch("openai.OpenAI")
    def test_embed_empty_list(self, mock_openai_cls: MagicMock):
        """Empty input → empty list."""
        mock_instance = MagicMock()
        mock_instance.embeddings.create.return_value = MagicMock(data=[])
        mock_openai_cls.return_value = mock_instance

        embedder = Embedder(
            base_url="https://api.openai.com/v1",
            api_key="test-key",
            model="text-embedding-3-small",
        )
        result = embedder.embed([])
        assert result == []
        mock_instance.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input=[],
        )
