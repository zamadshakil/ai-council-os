"""
rag_engine.py — Lightweight RAG Knowledge Hub

Architecture (optimized for Hostinger KVM4 / any server):
- LanceDB (disk-first, <30MB RAM) for vector storage
- OpenAI text-embedding-3-small via OpenRouter for embeddings ($0.02/1M tokens)
- Parent-child chunking: child=800 chars for search, parent=2800 chars for context
- SHA-256 deduplication — skips re-embedding identical documents
- Hybrid search: Dense vector + BM25 merged via Reciprocal Rank Fusion (RRF)
- FlashRank ONNX reranking (<35MB RAM, ~25ms rerank time)

Supported file types: PDF, DOCX, TXT, MD, CSV
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────
DATA_DIR = Path("./data")
LANCE_DIR = DATA_DIR / "lancedb"
META_DB_PATH = DATA_DIR / "rag_metadata.db"
EMBEDDING_DIM = 384  # sentence-transformers/all-MiniLM-L6-v2 dimensions

# ── Lazy-loaded singletons ─────────────────────────────────────────────────
_lance_db = None
_lance_table = None
_meta_conn = None


def _ensure_dirs():
    DATA_DIR.mkdir(exist_ok=True)
    LANCE_DIR.mkdir(exist_ok=True)


def _get_lance_db():
    global _lance_db
    if _lance_db is None:
        import lancedb
        _ensure_dirs()
        _lance_db = lancedb.connect(str(LANCE_DIR))
    return _lance_db


def get_table():
    """Get or create the LanceDB knowledge_base table."""
    global _lance_table
    if _lance_table is not None:
        return _lance_table

    db = _get_lance_db()
    table_name = "knowledge_base"

    import pyarrow as pa
    schema = pa.schema([
        pa.field("id", pa.string()),
        pa.field("text", pa.string()),
        pa.field("vector", pa.list_(pa.float32(), EMBEDDING_DIM)),
        pa.field("parent_text", pa.string()),
        pa.field("doc_hash", pa.string()),
        pa.field("doc_name", pa.string()),
        pa.field("chunk_index", pa.int32()),
    ])

    try:
        table = db.open_table(table_name)
        vec_field = table.schema.field("vector")
        if getattr(vec_field.type, 'list_size', None) == EMBEDDING_DIM:
            _lance_table = table
            return _lance_table
    except Exception:
        pass

    _lance_table = db.create_table(table_name, schema=schema, mode="overwrite")
    return _lance_table


def get_meta_conn() -> sqlite3.Connection:
    """Get SQLite metadata connection (tracks ingested files)."""
    global _meta_conn
    if _meta_conn is not None:
        return _meta_conn

    META_DB_PATH.parent.mkdir(exist_ok=True)
    _meta_conn = sqlite3.connect(str(META_DB_PATH), check_same_thread=False)
    _meta_conn.execute("""
        CREATE TABLE IF NOT EXISTS ingested_files (
            doc_hash  TEXT PRIMARY KEY,
            filename  TEXT NOT NULL,
            chunk_count INTEGER DEFAULT 0,
            ingested_at TEXT DEFAULT (datetime('now'))
        )
    """)
    _meta_conn.commit()
    return _meta_conn


# ── Embedding ──────────────────────────────────────────────────────────────

_embedding_model = None

async def get_embedding(text: str) -> list[float]:
    """
    Fetch a 384-dim embedding locally using sentence-transformers.
    Free, local, and bypasses OpenRouter API limits.
    """
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    
    text = text[:8000]  # safety truncate
    import asyncio
    loop = asyncio.get_event_loop()
    embedding = await loop.run_in_executor(None, _embedding_model.encode, text)
    return embedding.tolist()


# ── Document Parsing ───────────────────────────────────────────────────────

def _extract_text(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from PDF, DOCX, or text files."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf":
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            return "\n".join(page.get_text() for page in doc).strip()
        except ImportError:
            raise RuntimeError("PyMuPDF not installed. Run: pip install pymupdf")

    elif ext in (".docx", ".doc"):
        try:
            import docx
            import io
            doc = docx.Document(io.BytesIO(file_bytes))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        except ImportError:
            raise RuntimeError("python-docx not installed. Run: pip install python-docx")

    else:
        # TXT, MD, CSV — decode as text
        return file_bytes.decode("utf-8", errors="replace")


# ── Chunking ───────────────────────────────────────────────────────────────

def _chunk_document(text: str) -> list[tuple[str, str]]:
    """
    Hierarchical parent-child chunking:
    - Child (800 chars): used for dense vector retrieval (precision)
    - Parent (2800 chars): delivered to LLM as context (recall)
    Returns list of (child_text, parent_text) tuples.
    """
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    parent_splitter = RecursiveCharacterTextSplitter(chunk_size=2800, chunk_overlap=200)
    child_splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=100)

    parents = parent_splitter.split_text(text)
    pairs = []
    for parent in parents:
        children = child_splitter.split_text(parent)
        for child in children:
            if child.strip():
                pairs.append((child, parent))
    return pairs


# ── Ingestion ──────────────────────────────────────────────────────────────

async def ingest_document(file_bytes: bytes, filename: str) -> dict:
    """
    Ingest a document into the knowledge base.

    Returns:
        {"status": "ok"|"duplicate"|"empty", "chunks_indexed": int,
         "doc_hash": str, "filename": str}
    """
    doc_hash = hashlib.sha256(file_bytes).hexdigest()

    # Deduplication check
    conn = get_meta_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT doc_hash FROM ingested_files WHERE doc_hash = ?", (doc_hash,))
    if cursor.fetchone():
        return {"status": "duplicate", "chunks_indexed": 0,
                "doc_hash": doc_hash, "filename": filename}

    # Extract + chunk
    text = _extract_text(file_bytes, filename)
    if not text.strip():
        return {"status": "empty", "chunks_indexed": 0,
                "doc_hash": doc_hash, "filename": filename}

    pairs = _chunk_document(text)
    if not pairs:
        return {"status": "empty", "chunks_indexed": 0,
                "doc_hash": doc_hash, "filename": filename}

    # Embed and build records
    records = []
    for idx, (child, parent) in enumerate(pairs):
        vec = await get_embedding(child)
        records.append({
            "id": f"{doc_hash}_{idx}",
            "text": child,
            "vector": vec,
            "parent_text": parent,
            "doc_hash": doc_hash,
            "doc_name": filename,
            "chunk_index": idx,
        })

    # Store in LanceDB
    table = get_table()
    table.add(records)

    # Track in metadata
    conn.execute(
        "INSERT INTO ingested_files (doc_hash, filename, chunk_count) VALUES (?, ?, ?)",
        (doc_hash, filename, len(records)),
    )
    conn.commit()

    print(f"[RAG] Ingested '{filename}': {len(records)} chunks indexed.")
    return {"status": "ok", "chunks_indexed": len(records),
            "doc_hash": doc_hash, "filename": filename}


# ── Search ────────────────────────────────────────────────────────────────

def _bm25_score(query: str, documents: list[str]) -> list[float]:
    """BM25 keyword relevance scores."""
    try:
        from rank_bm25 import BM25Okapi
        tokenized = [doc.lower().split() for doc in documents]
        bm25 = BM25Okapi(tokenized)
        return bm25.get_scores(query.lower().split()).tolist()
    except ImportError:
        return [0.0] * len(documents)


def _rrf_merge(n: int, bm25_scores: list[float], k: int = 60) -> list[int]:
    """
    Reciprocal Rank Fusion: combine dense rank (positional) + BM25 rank.
    Returns indices sorted by combined RRF score (highest first).
    """
    rrf = [0.0] * n
    # Dense: positional rank (already ordered by vector distance)
    for rank in range(n):
        rrf[rank] += 1.0 / (k + rank + 1)
    # BM25 rank
    bm25_order = sorted(range(n), key=lambda i: bm25_scores[i], reverse=True)
    for rank, idx in enumerate(bm25_order):
        rrf[idx] += 1.0 / (k + rank + 1)
    return sorted(range(n), key=lambda i: rrf[i], reverse=True)


async def search_knowledge_base(query: str, top_k: int = 5, doc_hashes: Optional[list[str]] = None) -> list[dict]:
    """
    Hybrid vector + keyword search with FlashRank reranking.

    Returns:
        list of {"text": str, "doc_name": str, "doc_hash": str, "score": float}
    """
    table = get_table()

    # Check table has data
    try:
        if table.count_rows() == 0:
            return []
    except Exception:
        return []

    # 1. Dense vector retrieval (top 20 candidates)
    q_vec = await get_embedding(query)
    query_obj = table.search(q_vec)
    if doc_hashes:
        hashes_str = ", ".join([f"'{h}'" for h in doc_hashes])
        query_obj = query_obj.where(f"doc_hash IN ({hashes_str})")
    
    raw_results = query_obj.limit(20).to_list()
    if not raw_results:
        return []

    # Use parent_text for context delivery
    texts = [r.get("parent_text") or r["text"] for r in raw_results]

    # 2. BM25 scoring on candidates
    bm25_scores = _bm25_score(query, texts)

    # 3. RRF merge
    rrf_order = _rrf_merge(len(raw_results), bm25_scores)
    merged = [(raw_results[i], texts[i]) for i in rrf_order[:20]]

    # 4. FlashRank reranking
    try:
        from flashrank import Ranker, RerankRequest
        ranker = Ranker(model_name="ms-marco-TinyBERT-L-2-v2", cache_dir="/tmp/flashrank")
        passages = [{"id": str(i), "text": t} for i, (_, t) in enumerate(merged)]
        ranked = ranker.rerank(RerankRequest(query=query, passages=passages))

        seen, results = set(), []
        for r in ranked[:top_k]:
            t = r["text"]
            if t not in seen:
                seen.add(t)
                idx = int(r["id"])
                raw = merged[idx][0]
                results.append({
                    "text": t,
                    "doc_name": raw.get("doc_name", "unknown"),
                    "doc_hash": raw.get("doc_hash", ""),
                    "score": float(r.get("score", 0.8)),
                })
        return results

    except Exception as e:
        print(f"[RAG] FlashRank fallback (no reranking): {e}")
        seen, results = set(), []
        for raw, text in merged[:top_k]:
            if text not in seen:
                seen.add(text)
                results.append({
                    "text": text,
                    "doc_name": raw.get("doc_name", "unknown"),
                    "doc_hash": raw.get("doc_hash", ""),
                    "score": 0.8,
                })
        return results


# ── Document Management ────────────────────────────────────────────────────

async def get_all_documents() -> list[dict]:
    """List all ingested documents."""
    conn = get_meta_conn()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT doc_hash, filename, chunk_count, ingested_at FROM ingested_files ORDER BY ingested_at DESC"
    )
    return [
        {"doc_hash": r[0], "filename": r[1], "chunk_count": r[2], "ingested_at": r[3]}
        for r in cursor.fetchall()
    ]


async def delete_document(doc_hash: str) -> bool:
    """Remove a document from the knowledge base."""
    conn = get_meta_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT doc_hash FROM ingested_files WHERE doc_hash = ?", (doc_hash,))
    if not cursor.fetchone():
        return False

    try:
        table = get_table()
        table.delete(f"doc_hash = '{doc_hash}'")
    except Exception as e:
        print(f"[RAG] LanceDB delete warning: {e}")

    conn.execute("DELETE FROM ingested_files WHERE doc_hash = ?", (doc_hash,))
    conn.commit()
    return True


# ── Context Injection Helper ───────────────────────────────────────────────

async def get_rag_context(
    task_description: str,
    top_k: int = 3,
    doc_hashes: Optional[list[str]] = None,
) -> str:
    """
    Retrieve top-k relevant knowledge chunks for a council task.
    Returns a formatted string ready to inject into LLM prompts.
    Returns empty string if no knowledge base or no results.

    If doc_hashes is provided, search is restricted to only those documents
    instead of the entire knowledge base — lets a specific task/council run
    target only the relevant docs as the knowledge base grows.
    """
    try:
        results = await search_knowledge_base(task_description, top_k=top_k, doc_hashes=doc_hashes)
        if not results:
            return ""
        parts = [
            f"[Knowledge Context {i+1} — Source: {r['doc_name']}]\n{r['text']}"
            for i, r in enumerate(results)
        ]
        return "\n\n---\n\n".join(parts)
    except Exception as e:
        print(f"[RAG] Context retrieval error (non-fatal): {e}")
        return ""
