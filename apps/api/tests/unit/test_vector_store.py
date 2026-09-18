"""Unit tests for backend.rag.vector_store.

Uses real ChromaDB in tmp_path (not mocked) per design.md Decision 9.
These test the ChromaDB wrapper in isolation without FastAPI.
"""

import pytest

from backend.rag.vector_store import VectorStore, Hit, CollectionStats


@pytest.fixture
def store(tmp_path):
    """Fresh VectorStore backed by a temporary directory."""
    return VectorStore(persist_dir=str(tmp_path))


class TestListCollections:
    def test_empty_db_returns_empty_list(self, store):
        """No collections → empty list."""
        assert store.list_collections() == []

    def test_after_upsert_collection_present(self, store):
        """After upserting to a new collection, it appears in list_collections."""
        store.upsert(
            name="test-col",
            ids=["id-0"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["doc text"],
            metadatas=[{"source": "test.md"}],
        )
        assert "test-col" in store.list_collections()


class TestDeleteCollection:
    def test_delete_removes_collection(self, store):
        """delete_collection removes the named collection."""
        store.upsert(
            name="to-delete",
            ids=["id-0"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["doc text"],
            metadatas=[{"source": "test.md"}],
        )
        assert "to-delete" in store.list_collections()
        store.delete_collection("to-delete")
        assert "to-delete" not in store.list_collections()

    def test_delete_nonexistent_is_idempotent(self, store):
        """Deleting a non-existent collection does not raise."""
        store.delete_collection("does-not-exist")  # Should not raise


class TestUpsert:
    def test_upsert_single_document(self, store):
        """One upsert with one document can be queried back."""
        store.upsert(
            name="test-col",
            ids=["id-0"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["hello world"],
            metadatas=[{"source": "test.md"}],
        )
        hits = store.query(
            name="test-col",
            embedding=[0.1, 0.2, 0.3],
            top_k=1,
            threshold=0.0,
        )
        assert len(hits) == 1
        assert hits[0].text == "hello world"

    def test_upsert_multiple_documents(self, store):
        """Multiple documents in one upsert."""
        ids = ["id-0", "id-1", "id-2"]
        embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6], [0.7, 0.8, 0.9]]
        documents = ["doc a", "doc b", "doc c"]
        metadatas = [{"n": i} for i in range(3)]

        store.upsert("test-col", ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

        hits = store.query("test-col", embedding=[0.4, 0.5, 0.6], top_k=3, threshold=0.0)
        assert len(hits) == 3

    def test_upsert_then_upsert_replaces(self, store):
        """Re-upserting the same IDs replaces documents (idempotency)."""
        store.upsert(
            name="test-col",
            ids=["id-0"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["original"],
            metadatas=[{"v": 1}],
        )
        store.upsert(
            name="test-col",
            ids=["id-0"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["replaced"],
            metadatas=[{"v": 2}],
        )
        hits = store.query("test-col", embedding=[0.1, 0.2, 0.3], top_k=1, threshold=0.0)
        assert len(hits) == 1
        assert hits[0].text == "replaced"
        assert hits[0].metadata["v"] == 2


class TestQuery:
    def test_query_unknown_collection_returns_empty(self, store):
        """Querying a non-existent collection returns [].}"""
        hits = store.query("nonexistent", embedding=[0.1, 0.2, 0.3], top_k=5, threshold=0.0)
        assert hits == []

    def test_query_returns_hits_sorted_by_score_desc(self, store):
        """Results are ordered by descending score."""
        # Insert 3 documents with distinct embeddings
        store.upsert(
            name="test-col",
            ids=["id-0", "id-1", "id-2"],
            embeddings=[
                [1.0, 0.0, 0.0],  # identical to query → score 1.0
                [0.5, 0.5, 0.0],  # partial overlap
                [0.0, 0.1, 0.0],  # low overlap (positive score with threshold=-1)
            ],
            documents=["exact", "partial", "low"],
            metadatas=[{"i": 0}, {"i": 1}, {"i": 2}],
        )
        hits = store.query(
            name="test-col",
            embedding=[1.0, 0.0, 0.0],
            top_k=3,
            threshold=-1.0,  # negative threshold so all results pass
        )
        assert len(hits) == 3
        scores = [h.score for h in hits]
        assert scores == sorted(scores, reverse=True)
        assert hits[0].text == "exact"

    def test_query_threshold_filters_below_threshold(self, store):
        """Hits with score < threshold are excluded."""
        store.upsert(
            name="test-col",
            ids=["id-0", "id-1"],
            embeddings=[
                [1.0, 0.0, 0.0],  # exact match
                [0.1, 0.1, 0.0],  # low similarity
            ],
            documents=["high", "low"],
            metadatas=[{"i": 0}, {"i": 1}],
        )
        hits = store.query(
            name="test-col",
            embedding=[1.0, 0.0, 0.0],
            top_k=4,
            threshold=0.75,
        )
        # Only the exact match (score ~1.0) should pass threshold
        assert all(h.score >= 0.75 for h in hits)

    def test_query_top_k_limits_results(self, store):
        """top_k caps the number of returned hits."""
        # Insert 6 documents
        base = [1.0, 0.0, 0.0]
        for i in range(6):
            # Slightly different embeddings
            emb = [base[0] - i * 0.15, base[1], base[2]]
            store.upsert(
                name="test-col",
                ids=[f"id-{i}"],
                embeddings=[emb],
                documents=[f"doc-{i}"],
                metadatas=[{"i": i}],
            )
        hits = store.query(name="test-col", embedding=base, top_k=4, threshold=0.0)
        assert len(hits) <= 4

    def test_hit_namedtuple_fields(self, store):
        """Each Hit has text, metadata, and score fields."""
        store.upsert(
            name="test-col",
            ids=["id-0"],
            embeddings=[[0.1, 0.2, 0.3]],
            documents=["the text"],
            metadatas=[{"source": "manual.md", "page": 1}],
        )
        hits = store.query(name="test-col", embedding=[0.1, 0.2, 0.3], top_k=1, threshold=0.0)
        assert len(hits) == 1
        hit = hits[0]
        assert isinstance(hit, Hit)
        assert hit.text == "the text"
        assert hit.metadata["source"] == "manual.md"
        assert isinstance(hit.score, float)


class TestStats:
    def test_stats_empty_returns_empty(self, store):
        """No collections → empty stats."""
        assert store.stats() == []

    def test_stats_returns_collection_counts(self, store):
        """stats() returns correct chunk counts per collection."""
        store.upsert(
            name="col-a",
            ids=["id-0", "id-1"],
            embeddings=[[0.1], [0.2]],
            documents=["a", "b"],
            metadatas=[{"c": "a"}, {"c": "b"}],
        )
        store.upsert(
            name="col-b",
            ids=["id-0"],
            embeddings=[[0.3]],
            documents=["c"],
            metadatas=[{"c": "c"}],
        )
        stats = store.stats()
        assert len(stats) == 2
        names = {s.name for s in stats}
        assert names == {"col-a", "col-b"}
        by_name = {s.name: s.chunk_count for s in stats}
        assert by_name["col-a"] == 2
        assert by_name["col-b"] == 1

    def test_collection_stats_namedtuple(self, store):
        """CollectionStats has name and chunk_count fields."""
        store.upsert(
            name="test-col",
            ids=["id-0"],
            embeddings=[[0.1]],
            documents=["doc"],
            metadatas=[{"source": "test.md"}],
        )
        stats = store.stats()
        assert len(stats) == 1
        s = stats[0]
        assert isinstance(s, CollectionStats)
        assert s.name == "test-col"
        assert isinstance(s.chunk_count, int)
