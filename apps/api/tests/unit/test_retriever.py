"""Unit tests for backend.rag.retriever.

REQ-CHS-002 four scenarios:
  (a) zero hits above threshold → empty list
  (b) 3 hits below top_k → 3 chunks returned
  (c) exactly 4 hits → 4 chunks ordered desc
  (d) 6 hits → top 4 returned

The store and embedder are mocked.
"""

from unittest.mock import MagicMock

from backend.rag.retriever import Retriever
from backend.rag.vector_store import Hit


class TestRetrieve:
    """Retriever top-K + threshold semantics (REQ-CHS-002)."""

    def _make_retriever(self, mock_store, mock_embedder):
        return Retriever(store=mock_store, embedder=mock_embedder)

    def test_zero_hits_below_threshold_returns_empty(self):
        """REQ-CHS-002 (a): question with nearest chunk similarity 0.60 → empty."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        # Store returns 1 hit with score below threshold
        mock_store.query.return_value = [
            Hit(text="doc", metadata={}, score=0.60),
        ]

        retriever = self._make_retriever(mock_store, mock_embedder)
        result = retriever.retrieve("what is x?", "test-col", top_k=4, threshold=0.75)

        assert result == []
        mock_embedder.embed.assert_called_once_with(["what is x?"])
        mock_store.query.assert_called_once()

    def test_fewer_than_top_k_above_threshold_returns_all(self):
        """REQ-CHS-002 (b): similarities [0.92, 0.85, 0.78] → 3 chunks."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        mock_store.query.return_value = [
            Hit(text="doc a", metadata={}, score=0.92),
            Hit(text="doc b", metadata={}, score=0.85),
            Hit(text="doc c", metadata={}, score=0.78),
        ]

        retriever = self._make_retriever(mock_store, mock_embedder)
        result = retriever.retrieve("what is x?", "test-col", top_k=4, threshold=0.75)

        assert len(result) == 3
        texts = [h.text for h in result]
        assert texts == ["doc a", "doc b", "doc c"]

    def test_exactly_top_k_returns_all_ordered_desc(self):
        """REQ-CHS-002 (c): exactly 4 hits → 4 chunks ordered by descending score."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        # Store returns hits sorted desc by score (as per vector_store contract)
        mock_store.query.return_value = [
            Hit(text="doc a", metadata={}, score=0.95),
            Hit(text="doc b", metadata={}, score=0.88),
            Hit(text="doc c", metadata={}, score=0.81),
            Hit(text="doc d", metadata={}, score=0.76),
        ]

        retriever = self._make_retriever(mock_store, mock_embedder)
        result = retriever.retrieve("what is x?", "test-col", top_k=4, threshold=0.75)

        assert len(result) == 4
        scores = [h.score for h in result]
        assert scores == sorted(scores, reverse=True)

    def test_more_than_top_k_returns_only_top_k(self):
        """REQ-CHS-002 (d): 6 hits → top 4 returned."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        # Store returns 6 hits (already sorted desc)
        mock_store.query.return_value = [
            Hit(text=f"doc {i}", metadata={}, score=1.0 - i * 0.03)
            for i in range(6)
        ]

        retriever = self._make_retriever(mock_store, mock_embedder)
        result = retriever.retrieve("what is x?", "test-col", top_k=4, threshold=0.0)

        assert len(result) == 4
        # Top 4 by score
        assert result[0].text == "doc 0"
        assert result[3].text == "doc 3"

    def test_store_returns_unsorted_hits_retriever_sorts_desc(self):
        """If store returns unsorted hits, retriever re-sorts by score descending."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        # Hits returned in ascending order (violating store contract)
        mock_store.query.return_value = [
            Hit(text="low", metadata={}, score=0.76),
            Hit(text="high", metadata={}, score=0.95),
        ]

        retriever = self._make_retriever(mock_store, mock_embedder)
        result = retriever.retrieve("what is x?", "test-col", top_k=4, threshold=0.75)

        # Retriever always sorts by score descending
        assert len(result) == 2
        assert [h.text for h in result] == ["high", "low"]

    def test_threshold_applied_after_top_k_from_store(self):
        """Threshold filter is applied to the top_k results from store."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        # Store returns 4 hits, but one is below threshold
        mock_store.query.return_value = [
            Hit(text="doc a", metadata={}, score=0.95),
            Hit(text="doc b", metadata={}, score=0.85),
            Hit(text="doc c", metadata={}, score=0.72),  # below 0.75
            Hit(text="doc d", metadata={}, score=0.60),  # below 0.75
        ]

        retriever = self._make_retriever(mock_store, mock_embedder)
        result = retriever.retrieve("what is x?", "test-col", top_k=4, threshold=0.75)

        assert len(result) == 2
        assert all(h.score >= 0.75 for h in result)
        assert [h.text for h in result] == ["doc a", "doc b"]

    def test_retriever_uses_default_top_k_and_threshold(self):
        """Defaults: top_k=4, threshold=0.75; store gets top_k*3 for over-fetch."""
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store = MagicMock()
        mock_store.query.return_value = []

        retriever = self._make_retriever(mock_store, mock_embedder)
        retriever.retrieve("q", "test-col")  # no explicit top_k/threshold

        mock_store.query.assert_called_once_with(
            name="test-col",
            embedding=[0.1, 0.2, 0.3],
            top_k=12,  # over-fetch = top_k * 3 for threshold buffering
            threshold=0.0,  # internal threshold is 0.0; filtering happens in retriever
        )


class TestThresholdPropagation:
    """Regression tests for threshold propagation (GitHub issue: ChatService
    calling retriever.retrieve() without threshold caused hardcoded 0.75 default
    to be used regardless of settings.SIMILARITY_THRESHOLD)."""

    def test_retriever_default_threshold_is_0_75(self):
        """Retriever instantiated without threshold kwarg stores 0.75 as default."""
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        retriever = Retriever(store=mock_store, embedder=mock_embedder)
        assert retriever.threshold == 0.75

    def test_retriever_custom_threshold_stored(self):
        """Retriever instantiated with threshold=X stores X and exposes it via property."""
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        retriever = Retriever(store=mock_store, embedder=mock_embedder, threshold=0.1)
        assert retriever.threshold == 0.1

    def test_retriever_retrieve_uses_instance_threshold_when_caller_passes_none(self):
        """When retrieve() is called with threshold=None, it uses the instance default."""
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        # Two hits: 0.05 and 0.15. Instance threshold is 0.1, so only 0.15 passes.
        mock_store.query.return_value = [
            Hit(text="low", metadata={}, score=0.05),
            Hit(text="high", metadata={}, score=0.15),
        ]

        retriever = Retriever(store=mock_store, embedder=mock_embedder, threshold=0.1)
        hits = retriever.retrieve("q", "col", top_k=4, threshold=None)

        assert len(hits) == 1
        assert hits[0].score == 0.15
        assert hits[0].text == "high"

    def test_retriever_retrieve_caller_threshold_overrides_instance(self):
        """When retrieve() is called with an explicit threshold, it overrides the instance default."""
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        # Two hits: 0.05 and 0.15. Call threshold=0.05, so both pass.
        mock_store.query.return_value = [
            Hit(text="low", metadata={}, score=0.05),
            Hit(text="high", metadata={}, score=0.15),
        ]

        retriever = Retriever(store=mock_store, embedder=mock_embedder, threshold=0.1)
        hits = retriever.retrieve("q", "col", top_k=4, threshold=0.05)

        assert len(hits) == 2
        scores = [h.score for h in hits]
        assert scores == [0.15, 0.05]

    def test_retriever_retrieve_legacy_signature_still_works(self):
        """ChatService.stream_answer calls retriever.retrieve(question, resolved) with no
        threshold kwarg. This must still work — using the instance default threshold."""
        mock_store = MagicMock()
        mock_embedder = MagicMock()
        mock_embedder.embed.return_value = [[0.1, 0.2, 0.3]]

        mock_store.query.return_value = [
            Hit(text="doc", metadata={}, score=0.92),
        ]

        retriever = Retriever(store=mock_store, embedder=mock_embedder, threshold=0.1)
        # Call without threshold kwarg — mirrors what ChatService.stream_answer does
        result = retriever.retrieve("what is x?", "test-col")

        assert len(result) == 1
        assert result[0].score == 0.92
