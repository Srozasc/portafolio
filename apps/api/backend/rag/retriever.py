"""Threshold-gated retriever.

See design.md Module Layout / REQ-CHS-002.
Embeds the question, queries the vector store, and returns top-K hits
that meet the similarity threshold.
"""

from __future__ import annotations

from backend.rag.embedder import Embedder
from backend.rag.vector_store import Hit, VectorStore


class Retriever:
    """Embed-then-search retriever with top-K and similarity threshold."""

    def __init__(
        self,
        store: VectorStore,
        embedder: Embedder,
        *,
        threshold: float = 0.75,
    ) -> None:
        """Initialise the retriever.

        Args:
            store: VectorStore instance for ChromaDB lookups.
            embedder: Embedder instance for encoding queries.
            threshold: Default minimum similarity score for retrievals.
                Stored on the instance so callers don't have to pass it on
                every retrieve() call. Can be overridden per call.
        """
        self._store = store
        self._embedder = embedder
        self._threshold = threshold

    @property
    def threshold(self) -> float:
        """Return the configured default similarity threshold."""
        return self._threshold

    def retrieve(
        self,
        question: str,
        collection: str,
        *,
        top_k: int = 4,
        threshold: float | None = None,
    ) -> list[Hit]:
        """Retrieve the top-K chunks above the similarity threshold.

        Algorithm:
          1. Embed the question via embedder.embed([question])[0].
          2. Call store.query(collection, embedding, top_k, threshold=0.0)
             to get raw hits (we use threshold=0.0 internally to avoid
             ChromaDB dropping results we want to consider).
          3. Filter hits: keep only those with score >= threshold.
          4. Take at most top_k from the filtered set.
          5. Return hits ordered by score descending.

        Args:
            question: User's question string.
            collection: ChromaDB collection name.
            top_k: Maximum number of chunks to retrieve.
            threshold: Minimum similarity score. If None, uses the
                instance default set at construction (recommended).

        Returns:
            List of Hit namedtuples meeting the threshold, ordered by
            score descending. Empty list if no hits pass the threshold.
        """
        effective_threshold = threshold if threshold is not None else self._threshold

        # Embed the question
        embeddings = self._embedder.embed([question])
        question_embedding = embeddings[0]

        # Query the store — request more than top_k to account for threshold filtering
        hits = self._store.query(
            name=collection,
            embedding=question_embedding,
            top_k=top_k * 3,  # over-fetch to cover threshold filtering
            threshold=0.0,
        )

        # Filter by threshold
        filtered = [h for h in hits if h.score >= effective_threshold]

        # Return top_k of the threshold-filtered set, sorted desc
        return sorted(filtered[:top_k], key=lambda h: h.score, reverse=True)
