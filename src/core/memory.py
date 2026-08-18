"""
memory.py — Memory Architecture

Handles both short-term (conversation/task state) and long-term
(vector embeddings for semantic search) memory.

Short-term: Managed by LangGraph's built-in checkpointer (SQLite/Postgres).
Long-term:  ChromaDB (dev) or pgvector via Supabase (production).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

load_dotenv()


# ── ChromaDB for local development ──────────────────────────────────────

_chroma_client = None


def get_chroma_client():
    """Lazy-load ChromaDB client (only when needed)."""
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path="./chroma_data")
    return _chroma_client


def get_or_create_collection(name: str):
    """Get or create a ChromaDB collection."""
    client = get_chroma_client()
    return client.get_or_create_collection(name=name)


# ── Knowledge Base Operations ────────────────────────────────────────────

async def store_document(
    collection_name: str,
    document: str,
    metadata: dict[str, Any] | None = None,
    doc_id: str | None = None,
) -> str:
    """
    Store a document in the knowledge base.

    Args:
        collection_name: Which collection (e.g., "grants", "sales_calls", "content")
        document: The text content to store
        metadata: Optional metadata (source, tags, council, etc.)
        doc_id: Optional document ID (auto-generated if not provided)

    Returns:
        The document ID
    """
    import uuid

    collection = get_or_create_collection(collection_name)
    doc_id = doc_id or str(uuid.uuid4())

    meta = metadata or {}
    meta["stored_at"] = datetime.now(timezone.utc).isoformat()

    collection.add(
        documents=[document],
        metadatas=[meta],
        ids=[doc_id],
    )

    return doc_id


async def search_knowledge(
    collection_name: str,
    query: str,
    n_results: int = 5,
    where: dict | None = None,
) -> list[dict]:
    """
    Search the knowledge base semantically.

    Args:
        collection_name: Which collection to search
        query: Natural language query
        n_results: How many results to return
        where: Optional metadata filter

    Returns:
        List of dicts with 'document', 'metadata', 'distance'
    """
    collection = get_or_create_collection(collection_name)

    kwargs = {
        "query_texts": [query],
        "n_results": n_results,
    }
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    # Flatten results
    docs = []
    for i in range(len(results["documents"][0])):
        docs.append({
            "document": results["documents"][0][i],
            "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
            "distance": results["distances"][0][i] if results["distances"] else None,
        })

    return docs


async def store_feedback(
    task_id: str,
    council_name: str,
    approved: bool,
    original_output: str,
    edited_output: str = "",
    notes: str = "",
):
    """
    Store human feedback as a learning signal.

    When the human rejects or edits a council output, we embed
    that feedback into the knowledge base so future councils
    can retrieve it as "guidelines" during generation.
    """
    feedback_doc = (
        f"COUNCIL: {council_name}\n"
        f"APPROVED: {approved}\n"
        f"ORIGINAL OUTPUT:\n{original_output}\n"
    )

    if edited_output:
        feedback_doc += f"\nHUMAN EDITED VERSION:\n{edited_output}\n"
    if notes:
        feedback_doc += f"\nHUMAN NOTES:\n{notes}\n"

    await store_document(
        collection_name="feedback_history",
        document=feedback_doc,
        metadata={
            "task_id": task_id,
            "council": council_name,
            "approved": approved,
            "type": "human_feedback",
        },
    )


async def get_relevant_guidelines(
    council_name: str,
    task_description: str,
    n_results: int = 3,
) -> list[str]:
    """
    Retrieve past human feedback relevant to the current task.

    This is how councils "learn" from past approvals/rejections.
    The retrieved guidelines get injected into the Generator's prompt.
    """
    results = await search_knowledge(
        collection_name="feedback_history",
        query=task_description,
        n_results=n_results,
        where={"council": council_name},
    )

    return [r["document"] for r in results]
