"""ChromaDB PersistentClient wrapper.

See design.md Module Layout / Decision 9.
Wraps chromadb.PersistentClient with typed upsert/query/list/delete methods
and named tuples for query hits and collection stats.
"""

from __future__ import annotations

from typing import NamedTuple

import chromadb


class Hit(NamedTuple):
    """A single retrieved chunk from a query result."""
    text: str
    metadata: dict
    score: float


class CollectionStats(NamedTuple):
    """Statistics for one ChromaDB collection."""
    name: str
    chunk_count: int


class VectorStore:
    """Persistent ChromaDB client wrapper."""

    def __init__(self, persist_dir: str) -> None:
        """Open (or create) a PersistentClient at persist_dir.

        Args:
            persist_dir: Directory path for ChromaDB persistence.
        """
        self._client = chromadb.PersistentClient(path=persist_dir)

    # ---------------------------------------------------------------------------
    # Collection management
    # ---------------------------------------------------------------------------

    def list_collections(self) -> list[str]:
        """Return names of all collections."""
        # ChromaDB 0.6.x returns CollectionName objects (str subclasses)
        return [str(col) for col in self._client.list_collections()]

    def get_or_create(self, name: str) -> chromadb.Collection:
        """Return an existing collection by name or create it if it doesn't exist."""
        return self._client.get_or_create_collection(name=name)

    def delete_collection(self, name: str) -> None:
        """Delete a collection by name. Idempotent (no-op if not found)."""
        try:
            self._client.delete_collection(name=name)
        except ValueError:
            # ChromaDB 0.6.x raises ValueError when collection doesn't exist
            pass

    # ---------------------------------------------------------------------------
    # Document operations
    # ---------------------------------------------------------------------------

    def upsert(
        self,
        name: str,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        """Insert or replace documents in a collection.

        Args:
            name: Collection name.
            ids: Unique IDs for each document.
            embeddings: Dense embedding vectors (list of lists).
            documents: Raw text documents.
            metadatas: Metadata dicts, one per document.
        """
        collection = self._client.get_or_create_collection(name=name)
        # ChromaDB 0.6.x requires non-empty metadata dicts; use None for empty
        cleaned_metadatas = [m if m else None for m in metadatas]
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=cleaned_metadatas,
        )

    def query(
        self,
        name: str,
        embedding: list[float],
        top_k: int,
        threshold: float,
    ) -> list[Hit]:
        """Query a collection for the top-K nearest embeddings.

        Applies a similarity threshold filter (score >= threshold) after
        retrieving from ChromaDB.

        Args:
            name: Collection name.
            embedding: Query embedding vector.
            top_k: Maximum number of results to return.
            threshold: Minimum cosine similarity score (0.0–1.0).

        Returns:
            List of Hit namedtuples ordered by score descending.
        """
        try:
            collection = self._client.get_collection(name=name)
        except Exception:
            return []

        results = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        hits: list[Hit] = []
        # Results are keyed by query index (we sent one query, index 0)
        if not results or not results.get("documents") or not results["documents"][0]:
            return []

        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB distance is Euclidean; convert to cosine-like similarity
            # For normalised vectors: similarity = 1 - distance
            score = 1.0 - dist
            if score >= threshold:
                hits.append(Hit(text=doc, metadata=meta or {}, score=score))

        # Sort descending by score
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits

    # ---------------------------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------------------------

    def stats(self) -> list[CollectionStats]:
        """Return chunk counts for all collections.

        Returns:
            List of CollectionStats namedtuples (one per collection).
        """
        stats: list[CollectionStats] = []
        for col in self._client.list_collections():
            # ChromaDB 0.6.x: list_collections returns CollectionName (str subclass) objects
            col_name = str(col)
            try:
                collection = self._client.get_collection(col_name)
                count = collection.count()
            except Exception:
                count = 0
            stats.append(CollectionStats(name=col_name, chunk_count=count))
        return stats
