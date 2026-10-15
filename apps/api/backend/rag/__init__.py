"""RAG subsystem — pure logic, no FastAPI imports.

Modules:
    chunker   — markdown-aware token-based splitter. See design.md Decision 1.
    embedder  — OpenAI-compatible embedding client. See design.md Decision 6.
    vector_store — ChromaDB PersistentClient wrapper. See design.md Module Layout.
    retriever — embed(q) -> top-K hits above threshold.
    llm_client — OpenAI-compatible streaming chat client. See design.md Decision 3.
    prompts   — SYSTEM_PROMPT_TEMPLATE verbatim from design doc §8.
"""

from backend.rag import chunker, embedder, llm_client, prompts, retriever, vector_store

__all__ = ["chunker", "embedder", "llm_client", "prompts", "retriever", "vector_store"]
