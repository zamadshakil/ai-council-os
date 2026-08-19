"""Native PostgreSQL/pgvector knowledge ingestion and retrieval.

PostgreSQL is the production authority. SQLite uses the same SQLAlchemy models
for development and tests; legacy LanceDB/metadata paths are retired.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

from sqlalchemy import delete, func, literal, or_, select

from src.core import database as db
from src.core.models import (
    BrainConflictModel, BrainEntityAliasModel, BrainFactModel, BrainRelationshipModel,
    KnowledgeChunkModel, KnowledgeCollectionModel,
    KnowledgeCollectionDocumentModel, KnowledgeDocumentModel,
    RetrievalCacheModel, iso, utcnow,
)

EMBEDDING_DIM = 384
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
INDEX_VERSION = 2
PIPELINE_VERSION = "native-brain-v1"
CACHE_TTL = timedelta(minutes=20)
MAX_CANDIDATES = 40

_embedding_model: Any = None
_reranker_model: Any = None
_embedding_cache: dict[str, list[float]] = {}


class KnowledgeRetrievalError(RuntimeError):
    """Visible retrieval failure; callers must not reinterpret it as no evidence."""


def _as_utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_text(text: str) -> str:
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _extract_text(file_bytes: bytes, filename: str) -> tuple[str, list[str]]:
    warnings: list[str] = []
    extension = Path(filename).suffix.lower()
    if extension == ".pdf":
        import fitz
        document = fitz.open(stream=file_bytes, filetype="pdf")
        pages: list[str] = []
        for number, page in enumerate(document, start=1):
            value = page.get_text().strip()
            if not value:
                warnings.append(f"Page {number} contained no extractable text.")
            pages.append(value)
        text = "\n\n".join(pages)
    elif extension == ".docx":
        import io
        import docx
        document = docx.Document(io.BytesIO(file_bytes))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    elif extension in {".txt", ".md"}:
        text = file_bytes.decode("utf-8", errors="replace")
        if "\ufffd" in text:
            warnings.append("Invalid UTF-8 bytes were replaced during extraction.")
    else:
        raise ValueError("Only PDF, DOCX, TXT, and Markdown documents are supported.")
    return _normalize_text(text), warnings


def _chunk_document_with_spans(text: str) -> list[dict[str, Any]]:
    """Create overlapping parent/child passages with verifiable character spans."""
    if not text.strip():
        return []
    parent_size, parent_overlap = 2800, 240
    child_size, child_overlap = 800, 120
    chunks: list[dict[str, Any]] = []
    parent_start = parent_number = 0
    while parent_start < len(text):
        parent_end = min(len(text), parent_start + parent_size)
        if parent_end < len(text):
            boundary = text.rfind("\n", parent_start + 1200, parent_end)
            if boundary > parent_start:
                parent_end = boundary
        parent_slice = text[parent_start:parent_end]
        leading = len(parent_slice) - len(parent_slice.lstrip())
        parent = parent_slice.strip()
        parent_source_start = parent_start + leading
        if parent:
            child_local = 0
            while child_local < len(parent):
                child_end = min(len(parent), child_local + child_size)
                if child_end < len(parent):
                    boundary = max(
                        parent.rfind("\n", child_local + 320, child_end),
                        parent.rfind(". ", child_local + 320, child_end),
                    )
                    if boundary > child_local:
                        child_end = boundary + 1
                child = parent[child_local:child_end].strip()
                if child:
                    actual_local = parent.find(child, child_local)
                    start = parent_source_start + max(0, actual_local)
                    chunks.append({
                        "text": child, "parent_text": parent,
                        "source_start": start, "source_end": start + len(child),
                        "parent_key": f"p{parent_number}:{parent_source_start}:{parent_source_start + len(parent)}",
                    })
                if child_end >= len(parent):
                    break
                child_local = max(child_local + 1, child_end - child_overlap)
        if parent_end >= len(text):
            break
        parent_start = max(parent_start + 1, parent_end - parent_overlap)
        parent_number += 1
    return chunks


def _chunk_document(text: str) -> list[tuple[str, str]]:
    return [(item["text"], item["parent_text"]) for item in _chunk_document_with_spans(text)]


async def get_embedding(text: str) -> list[float]:
    return (await get_embeddings([text]))[0]


async def get_embeddings(texts: Sequence[str]) -> list[list[float]]:
    """Batch local embedding work and retain a bounded model-versioned cache."""
    global _embedding_model
    if not texts:
        return []
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = await asyncio.to_thread(SentenceTransformer, EMBEDDING_MODEL)

    keys = [hashlib.sha256(f"{EMBEDDING_MODEL}:{text[:8000]}".encode()).hexdigest() for text in texts]
    missing_positions = [index for index, key in enumerate(keys) if key not in _embedding_cache]

    if missing_positions:
        missing_texts = [texts[index][:8000] for index in missing_positions]

        def encode() -> list[list[float]]:
            vectors = _embedding_model.encode(
                missing_texts, normalize_embeddings=True, show_progress_bar=False,
            )
            return [[float(value) for value in vector.tolist()] for vector in vectors]

        encoded = await asyncio.to_thread(encode)
        for index, vector in zip(missing_positions, encoded, strict=True):
            if len(vector) != EMBEDDING_DIM:
                raise RuntimeError(
                    f"Embedding model returned {len(vector)} dimensions; expected {EMBEDDING_DIM}."
                )
            _embedding_cache[keys[index]] = vector
        while len(_embedding_cache) > 2048:
            _embedding_cache.pop(next(iter(_embedding_cache)))
    return [list(_embedding_cache[key]) for key in keys]


async def ingest_pending_document(document_id: str) -> dict[str, Any]:
    """Idempotently build one document index inside a durable worker job."""
    async with db.async_session() as session:
        document = await session.get(KnowledgeDocumentModel, document_id)
        if not document:
            raise ValueError("Knowledge document no longer exists.")
        metadata = dict(document.metadata_json or {})
        current_index = document.status == "ready" and document.indexing_version == INDEX_VERSION
        if current_index and metadata.get("graph_status") == "ready":
            count = await session.scalar(select(func.count(KnowledgeChunkModel.id)).where(KnowledgeChunkModel.document_id == document.id))
            return {"document_id": document.id, "status": "ready", "chunks_indexed": int(count or 0), "recovered": True}
        if current_index:
            count = int(await session.scalar(select(func.count(KnowledgeChunkModel.id)).where(
                KnowledgeChunkModel.document_id == document.id
            )) or 0)
            raw_content, filename = bytes(document.raw_content), document.filename
            stored_extraction_warnings = list(document.extraction_warnings or [])
        else:
            document.status, document.error = "indexing", ""
            metadata["graph_status"] = "pending"
            document.metadata_json = metadata
            document.version += 1
            await session.commit()
            count = 0
            raw_content, filename = bytes(document.raw_content), document.filename
            stored_extraction_warnings = []
    try:
        if current_index:
            pieces: list[dict[str, Any]] = []
            extraction_warnings = stored_extraction_warnings
        else:
            normalized_text, extraction_warnings = await asyncio.to_thread(_extract_text, raw_content, filename)
            if not normalized_text:
                raise ValueError("The document did not contain extractable text.")
            pieces = _chunk_document_with_spans(normalized_text)
            if not pieces:
                raise ValueError("The document did not contain indexable passages.")
            vectors = await get_embeddings([item["text"] for item in pieces])
            async with db.async_session() as session:
                document = await session.get(KnowledgeDocumentModel, document_id)
                if not document:
                    raise ValueError("Knowledge document was deleted while indexing.")
                await session.execute(delete(KnowledgeChunkModel).where(or_(
                    KnowledgeChunkModel.document_id == document.id,
                    KnowledgeChunkModel.doc_hash == document.sha256,
                )))
                for index, (piece, vector) in enumerate(zip(pieces, vectors, strict=True)):
                    session.add(KnowledgeChunkModel(
                        document_id=document.id, doc_hash=document.sha256,
                        doc_name=document.filename, chunk_index=index, vector=vector,
                        index_version=INDEX_VERSION, embedding_model=EMBEDDING_MODEL, **piece,
                    ))
                metadata = dict(document.metadata_json or {})
                metadata["graph_status"] = "pending"
                document.metadata_json = metadata
                document.normalized_text = normalized_text
                document.extraction_warnings = extraction_warnings
                document.indexing_version = INDEX_VERSION
                document.embedding_model = EMBEDDING_MODEL
                document.status, document.warning, document.error = "ready", "\n".join(extraction_warnings), ""
                document.version += 1
                await session.execute(delete(RetrievalCacheModel))
                await session.commit()
            count = len(pieces)
    except Exception as exc:
        async with db.async_session() as session:
            document = await session.get(KnowledgeDocumentModel, document_id)
            if document:
                document.status, document.error = "failed", str(exc)[:8000]
                document.warning = "Indexing failed. Open the document to inspect the error."
                document.version += 1
                await session.commit()
        raise

    try:
        from src.core.brain import extract_document_graph
        await extract_document_graph(document_id)
    except Exception as exc:
        graph_warning = f"Graph extraction failed and will be retried: {exc}"
        async with db.async_session() as session:
            document = await session.get(KnowledgeDocumentModel, document_id)
            if document:
                metadata = dict(document.metadata_json or {})
                metadata["graph_status"] = "failed"
                document.metadata_json = metadata
                warnings = [
                    warning for warning in (document.extraction_warnings or [])
                    if not str(warning).startswith("Graph extraction failed")
                ]
                warnings.append(graph_warning)
                document.extraction_warnings, document.warning = warnings, "\n".join(warnings)
                document.version += 1
                await session.commit()
        raise RuntimeError(graph_warning) from exc

    async with db.async_session() as session:
        document = await session.get(KnowledgeDocumentModel, document_id)
        if document:
            metadata = dict(document.metadata_json or {})
            metadata["graph_status"] = "ready"
            document.metadata_json = metadata
            warnings = [
                warning for warning in (document.extraction_warnings or [])
                if not str(warning).startswith("Graph extraction failed")
            ]
            document.extraction_warnings = warnings
            document.warning = "\n".join(warnings)
            document.version += 1
            extraction_warnings = warnings
            await session.commit()
    return {
        "document_id": document_id, "status": "ready", "chunks_indexed": count,
        "index_version": INDEX_VERSION, "warnings": extraction_warnings,
        "recovered": current_index,
    }


async def ingest_document(file_bytes: bytes, filename: str) -> dict[str, Any]:
    """Compatibility entry point using the authoritative SQL tables."""
    digest = hashlib.sha256(file_bytes).hexdigest()
    async with db.async_session() as session:
        document = (await session.execute(select(KnowledgeDocumentModel).where(KnowledgeDocumentModel.sha256 == digest))).scalar_one_or_none()
        if document and document.status == "ready":
            return {"status": "duplicate", "chunks_indexed": 0, "doc_hash": digest, "filename": filename}
        if document is None:
            document = KnowledgeDocumentModel(
                filename=Path(filename).name, content_type="application/octet-stream",
                size_bytes=len(file_bytes), sha256=digest, storage_key=digest,
                raw_content=file_bytes, status="pending",
            )
            session.add(document)
            await session.commit()
            await session.refresh(document)
        document_id = document.id
    result = await ingest_pending_document(document_id)
    return {"status": "ok", "chunks_indexed": result["chunks_indexed"], "doc_hash": digest, "filename": filename}


def _safe_hashes(values: Sequence[str] | None) -> list[str]:
    safe = [value.lower() for value in (values or []) if re.fullmatch(r"[a-fA-F0-9]{64}", value)]
    if len(safe) != len(values or []):
        raise ValueError("Invalid document hash in retrieval scope.")
    return list(dict.fromkeys(safe))


def _weighted_rrf(rankings: dict[str, list[str]], weights: dict[str, float], k: int = 60) -> dict[str, float]:
    fused: defaultdict[str, float] = defaultdict(float)
    for signal, identifiers in rankings.items():
        for rank, identifier in enumerate(identifiers):
            fused[identifier] += weights.get(signal, 1.0) / (k + rank + 1)
    return dict(fused)


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


async def _rerank(query: str, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    global _reranker_model
    warnings: list[str] = []
    if not items:
        return items, warnings
    try:
        if _reranker_model is None:
            from sentence_transformers import CrossEncoder
            _reranker_model = await asyncio.to_thread(CrossEncoder, RERANKER_MODEL)
        scores = await asyncio.to_thread(
            _reranker_model.predict, [(query, item["parent_text"]) for item in items],
            show_progress_bar=False,
        )
        for item, score in zip(items, scores, strict=True):
            item["reranker_score"] = float(score)
        items.sort(key=lambda item: item["reranker_score"], reverse=True)
    except Exception as exc:
        warnings.append(f"Cross-encoder reranking was unavailable: {exc}")
        items.sort(key=lambda item: item["fusion_score"], reverse=True)
    return items, warnings


def _mmr(items: list[dict[str, Any]], query_vector: list[float], top_k: int, lambda_value: float = 0.72) -> list[dict[str, Any]]:
    selected, candidates = [], list(items)
    seen_parents: set[str] = set()
    while candidates and len(selected) < top_k:
        scored: list[tuple[float, dict[str, Any]]] = []
        for item in candidates:
            if item.get("parent_key") in seen_parents:
                continue
            relevance = float(item.get("reranker_score", item.get("fusion_score", 0.0)))
            redundancy = max((_cosine(item["vector"], chosen["vector"]) for chosen in selected), default=0.0)
            semantic = _cosine(item["vector"], query_vector)
            scored.append((lambda_value * (relevance + semantic) - (1 - lambda_value) * redundancy, item))
        if not scored:
            break
        _, winner = max(scored, key=lambda pair: pair[0])
        selected.append(winner)
        seen_parents.add(str(winner.get("parent_key") or winner["id"]))
        candidates.remove(winner)
    return selected


async def _scope_hashes(
    collection_ids: Sequence[str], document_hashes: Sequence[str],
) -> tuple[list[str], list[dict[str, Any]]]:
    hashes = set(document_hashes)
    versions: list[dict[str, Any]] = []
    if collection_ids:
        async with db.async_session() as session:
            collections = (await session.execute(select(KnowledgeCollectionModel).where(
                KnowledgeCollectionModel.id.in_(list(collection_ids))
            ))).scalars().all()
            if len(collections) != len(set(collection_ids)):
                raise ValueError("One or more knowledge collections do not exist.")
            versions = [{"id": item.id, "version": item.version} for item in collections]
            rows = (await session.execute(
                select(KnowledgeDocumentModel.sha256)
                .join(KnowledgeCollectionDocumentModel, KnowledgeCollectionDocumentModel.document_id == KnowledgeDocumentModel.id)
                .where(KnowledgeCollectionDocumentModel.collection_id.in_(list(collection_ids)))
            )).scalars().all()
            hashes.update(rows)
    return sorted(hashes), versions


async def search_knowledge(
    query: str, *, top_k: int = 8,
    document_hashes: Sequence[str] | None = None,
    collection_ids: Sequence[str] | None = None,
    graph_expansion: bool = True,
) -> dict[str, Any]:
    """Run dense/lexical/exact/graph retrieval, one fusion, reranking, and MMR."""
    query = _normalize_text(query)[:2000]
    if not query:
        raise ValueError("Search query is required.")
    explicit_hashes, collections = _safe_hashes(document_hashes), list(dict.fromkeys(collection_ids or []))
    scoped_hashes, collection_versions = await _scope_hashes(collections, explicit_hashes)
    cached_query_vector: list[float] | None = None
    legacy_count = 0
    async with db.async_session() as session:
        index_version = int(await session.scalar(select(func.max(KnowledgeDocumentModel.indexing_version))) or 0)
        legacy_filters = [
            KnowledgeDocumentModel.status == "ready",
            KnowledgeDocumentModel.indexing_version < INDEX_VERSION,
        ]
        if explicit_hashes or collections:
            legacy_filters.append(KnowledgeDocumentModel.sha256.in_(scoped_hashes))
        legacy_count = int(await session.scalar(select(func.count(KnowledgeDocumentModel.id)).where(
            *legacy_filters
        )) or 0)
        scope_key = json.dumps({"documents": scoped_hashes, "collections": collections}, sort_keys=True)
        query_hash = hashlib.sha256(query.lower().encode()).hexdigest()
        scope_hash = hashlib.sha256(scope_key.encode()).hexdigest()
        cache_id = hashlib.sha256(f"{query_hash}:{scope_hash}:{EMBEDDING_MODEL}:{index_version}:{top_k}:{graph_expansion}".encode()).hexdigest()
        cached = await session.get(RetrievalCacheModel, cache_id)
        if cached and _as_utc(cached.expires_at) > utcnow():
            return {**(cached.result or {}), "cached": True}
        sibling = (await session.execute(select(RetrievalCacheModel).where(
            RetrievalCacheModel.query_hash == query_hash,
            RetrievalCacheModel.scope_hash == scope_hash,
            RetrievalCacheModel.model_version == EMBEDDING_MODEL,
            RetrievalCacheModel.index_version == index_version,
        ).order_by(RetrievalCacheModel.created_at.desc()).limit(1))).scalar_one_or_none()
        if sibling and sibling.query_vector:
            cached_query_vector = list(sibling.query_vector)
    query_vector = cached_query_vector or await get_embedding(query)
    try:
        items, rankings = await _candidate_sets(
            query, query_vector, scoped_hashes, graph_expansion,
            scope_restricted=bool(explicit_hashes or collections),
        )
        fusion = _weighted_rrf(rankings, {"dense": 1.0, "lexical": 0.9, "exact": 1.15, "graph": 0.75})
        candidates = [items[identifier] for identifier in fusion if identifier in items]
        for item in candidates:
            item["fusion_score"] = fusion[item["id"]]
        candidates.sort(key=lambda item: item["fusion_score"], reverse=True)
        candidates, warnings = await _rerank(query, candidates[:MAX_CANDIDATES])
        if legacy_count:
            warnings.append(
                f"{legacy_count} legacy source(s) remain lexical-only until their controlled BGE reindex completes."
            )
        selected = _mmr(candidates, query_vector, max(1, min(top_k, 20)))
        document_ids = {str(item.get("document_id") or "") for item in selected}
        async with db.async_session() as session:
            source_rows = (await session.execute(
                select(
                    KnowledgeDocumentModel.id, KnowledgeDocumentModel.normalized_text,
                    KnowledgeDocumentModel.version, KnowledgeDocumentModel.indexing_version,
                )
                .where(KnowledgeDocumentModel.id.in_(document_ids))
            )).all() if document_ids else []
        source_texts = {document_id: text for document_id, text, _, _ in source_rows}
        document_versions = {
            document_id: {"version": version, "index_version": document_index_version}
            for document_id, _, version, document_index_version in source_rows
        }
        results: list[dict[str, Any]] = []
        for rank, item in enumerate(selected, start=1):
            start, end = int(item.get("source_start") or 0), int(item.get("source_end") or 0)
            source_text = source_texts.get(item.get("document_id"), "")
            if (
                start < 0 or end <= start or not item.get("text")
                or end > len(source_text) or source_text[start:end] != item["text"]
            ):
                warnings.append(f"Dropped invalid citation span for passage {item.get('id', '')}.")
                continue
            results.append({
                "id": item["id"], "text": item["parent_text"], "matched_text": item["text"],
                "doc_name": item["doc_name"], "doc_hash": item["doc_hash"],
                "document_id": item.get("document_id"), "chunk_index": item["chunk_index"],
                "document_version": document_versions.get(item.get("document_id"), {}).get("version", 1),
                "fact_versions": item.get("fact_versions", []),
                "source_start": start, "source_end": end,
                "citation": f"{item['doc_name']} · characters {start + 1}–{end}",
                "score": float(item.get("reranker_score", item["fusion_score"])),
                "score_breakdown": {
                    "fusion": float(item["fusion_score"]), "dense": item.get("dense_score"),
                    "lexical": item.get("lexical_score"), "exact": item.get("exact_score"),
                    "graph": item.get("graph_score"), "reranker": item.get("reranker_score"), "rank": rank,
                },
            })
        response = {
            "results": results, "warnings": list(dict.fromkeys(warnings)), "query": query,
            "scope": {
                "document_hashes": scoped_hashes, "collection_ids": collections,
                "collections": collection_versions,
            },
            "pipeline": PIPELINE_VERSION, "embedding_model": EMBEDDING_MODEL,
            "index_version": index_version,
            "candidate_counts": {name: len(values) for name, values in rankings.items()}, "cached": False,
        }
    except Exception as exc:
        if isinstance(exc, (ValueError, KnowledgeRetrievalError)):
            raise
        raise KnowledgeRetrievalError(f"Knowledge retrieval failed: {exc}") from exc
    async with db.async_session() as session:
        session.add(RetrievalCacheModel(
            id=cache_id, query_hash=query_hash, scope_hash=scope_hash,
            model_version=EMBEDDING_MODEL, index_version=index_version,
            query_vector=query_vector, result=response, expires_at=utcnow() + CACHE_TTL,
        ))
        await session.commit()
    return response


async def _candidate_sets(
    query: str, query_vector: list[float], scoped_hashes: list[str],
    graph_expansion: bool, *, scope_restricted: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    items: dict[str, dict[str, Any]] = {}
    rankings: dict[str, list[str]] = {"dense": [], "lexical": [], "exact": [], "graph": []}
    async with db.async_session() as session:
        base_filter = [KnowledgeDocumentModel.status == "ready"]
        if scope_restricted:
            base_filter.append(KnowledgeChunkModel.doc_hash.in_(scoped_hashes))
        dialect = session.bind.dialect.name if session.bind else "sqlite"
        if dialect == "postgresql":
            distance = KnowledgeChunkModel.vector.cosine_distance(query_vector)
            dense_query = (select(KnowledgeChunkModel, distance.label("score"))
                .join(KnowledgeDocumentModel, KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id)
                .where(
                    *base_filter,
                    KnowledgeChunkModel.index_version == INDEX_VERSION,
                    KnowledgeChunkModel.embedding_model == EMBEDDING_MODEL,
                ).order_by(distance).limit(MAX_CANDIDATES))
            searchable = func.concat(KnowledgeChunkModel.parent_text, literal(" "), KnowledgeChunkModel.text)
            ts_query, ts_vector = func.plainto_tsquery("simple", query), func.to_tsvector("simple", searchable)
            lexical_score = func.ts_rank_cd(ts_vector, ts_query)
            lexical_query = (select(KnowledgeChunkModel, lexical_score.label("score"))
                .join(KnowledgeDocumentModel, KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id)
                .where(*base_filter, ts_vector.op("@@")(ts_query)).order_by(lexical_score.desc()).limit(MAX_CANDIDATES))
            dense_rows, lexical_rows = (await session.execute(dense_query)).all(), (await session.execute(lexical_query)).all()
        else:
            chunks = (await session.execute(select(KnowledgeChunkModel)
                .join(KnowledgeDocumentModel, KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id)
                .where(*base_filter))).scalars().all()
            current_chunks = [
                chunk for chunk in chunks
                if chunk.index_version == INDEX_VERSION and chunk.embedding_model == EMBEDDING_MODEL
            ]
            dense_rows = sorted([(chunk, 1.0 - _cosine(query_vector, list(chunk.vector))) for chunk in current_chunks], key=lambda row: row[1])[:MAX_CANDIDATES]
            terms = set(re.findall(r"[a-z0-9]+", query.lower()))
            lexical_rows = sorted([(chunk, len(terms & set(re.findall(r"[a-z0-9]+", (chunk.parent_text + " " + chunk.text).lower())))) for chunk in chunks], key=lambda row: row[1], reverse=True)[:MAX_CANDIDATES]

        def add(chunk: KnowledgeChunkModel, signal: str, score: float) -> dict[str, Any]:
            item = items.setdefault(chunk.id, {
                "id": chunk.id, "document_id": chunk.document_id, "doc_hash": chunk.doc_hash,
                "doc_name": chunk.doc_name, "chunk_index": chunk.chunk_index, "text": chunk.text,
                "parent_text": chunk.parent_text, "source_start": chunk.source_start,
                "source_end": chunk.source_end, "parent_key": chunk.parent_key, "vector": list(chunk.vector),
            })
            item[f"{signal}_score"], rankings[signal] = score, [*rankings[signal], chunk.id]
            return item
        for chunk, raw in dense_rows:
            add(chunk, "dense", 1.0 - float(raw))
        for chunk, raw in lexical_rows:
            if float(raw) > 0:
                add(chunk, "lexical", float(raw))
        terms = re.findall(r"[a-z0-9][a-z0-9_-]{2,}", query.lower())[:10]
        if terms:
            exact_query = (select(KnowledgeChunkModel)
                .join(KnowledgeDocumentModel, KnowledgeDocumentModel.id == KnowledgeChunkModel.document_id)
                .where(*base_filter, or_(*[func.lower(KnowledgeChunkModel.parent_text).contains(term) for term in terms]))
                .limit(MAX_CANDIDATES))
            for chunk in (await session.execute(exact_query)).scalars().all():
                add(chunk, "exact", float(sum(term in chunk.parent_text.lower() for term in terms)))
        if graph_expansion:
            query_tokens = re.findall(r"[a-z0-9]+", query.lower())
            alias_terms = {
                " ".join(query_tokens[start:end])
                for start in range(len(query_tokens))
                for end in range(start + 1, min(len(query_tokens), start + 5) + 1)
            }
            aliases = (await session.execute(select(
                BrainEntityAliasModel.entity_id,
            ).where(
                BrainEntityAliasModel.normalized_alias.in_(alias_terms)
            ))).scalars().all() if alias_terms else []
            entity_ids = list(dict.fromkeys(aliases))
            if entity_ids:
                relationship_rows = (await session.execute(select(
                    BrainRelationshipModel.source_entity_id,
                    BrainRelationshipModel.target_entity_id,
                    BrainRelationshipModel.source_fact_id,
                ).where(
                    BrainRelationshipModel.status == "verified",
                    or_(
                        BrainRelationshipModel.source_entity_id.in_(entity_ids),
                        BrainRelationshipModel.target_entity_id.in_(entity_ids),
                    ),
                ))).all()
                expanded_entity_ids = set(entity_ids)
                relationship_fact_ids: set[str] = set()
                for source_id, target_id, source_fact_id in relationship_rows:
                    expanded_entity_ids.update((source_id, target_id))
                    if source_fact_id:
                        relationship_fact_ids.add(source_fact_id)
                graph_facts = (await session.execute(select(
                    BrainFactModel.id, BrainFactModel.source_chunk_id, BrainFactModel.version,
                ).where(
                    or_(
                        BrainFactModel.subject_entity_id.in_(expanded_entity_ids),
                        BrainFactModel.id.in_(relationship_fact_ids),
                    ),
                    BrainFactModel.status == "verified",
                    BrainFactModel.source_chunk_id.is_not(None),
                ))).all()
                chunk_ids = [row.source_chunk_id for row in graph_facts]
                if chunk_ids:
                    graph_query = select(KnowledgeChunkModel).where(KnowledgeChunkModel.id.in_(chunk_ids))
                    if scope_restricted:
                        graph_query = graph_query.where(KnowledgeChunkModel.doc_hash.in_(scoped_hashes))
                    for chunk in (await session.execute(graph_query)).scalars().all():
                        item = add(chunk, "graph", 1.0)
                        item["fact_versions"] = [
                            {"id": row.id, "version": row.version}
                            for row in graph_facts if row.source_chunk_id == chunk.id
                        ]
    return items, {name: list(dict.fromkeys(values)) for name, values in rankings.items()}


async def search_knowledge_base(query: str, top_k: int = 5, doc_hashes: Sequence[str] | None = None) -> list[dict[str, Any]]:
    return (await search_knowledge(query, top_k=top_k, document_hashes=doc_hashes))["results"]


async def get_rag_context(task_description: str, top_k: int = 5, doc_hashes: Sequence[str] | None = None, collection_ids: Sequence[str] | None = None) -> str:
    response = await search_knowledge(task_description, top_k=top_k, document_hashes=doc_hashes, collection_ids=collection_ids)
    if not response["results"]:
        return ""
    sections = [f"[{item['citation']}]\n{item['text']}" for item in response["results"]]
    if response.get("warnings"):
        sections.append("Retrieval warnings:\n- " + "\n- ".join(response["warnings"]))
    return "\n\n---\n\n".join(sections)


async def get_all_documents() -> list[dict[str, Any]]:
    async with db.async_session() as session:
        documents = (await session.execute(select(KnowledgeDocumentModel).order_by(KnowledgeDocumentModel.created_at.desc()))).scalars().all()
        counts = dict((await session.execute(select(KnowledgeChunkModel.doc_hash, func.count(KnowledgeChunkModel.id)).group_by(KnowledgeChunkModel.doc_hash))).all())
    return [{
        "id": document.id, "doc_hash": document.sha256, "filename": document.filename,
        "chunk_count": int(counts.get(document.sha256, 0)), "status": document.status,
        "index_version": document.indexing_version, "embedding_model": document.embedding_model,
        "warning": document.warning, "error": document.error, "ingested_at": iso(document.created_at),
    } for document in documents]


async def delete_document(doc_hash: str) -> bool:
    async with db.async_session() as session:
        deleted = await delete_document_in_session(session, doc_hash)
        await session.commit()
        return deleted


async def delete_document_in_session(session, doc_hash: str) -> bool:
    """Delete a source and its provenance in the caller's transaction.

    The explicit ordering keeps local SQLite deterministic even when a test or
    legacy connection was opened before foreign-key enforcement was enabled.
    Shared canonical entities remain because they can be referenced by other
    documents; source facts, edges, conflicts, chunks, and memberships do not.
    """
    document = (await session.execute(select(KnowledgeDocumentModel).where(
        KnowledgeDocumentModel.sha256 == doc_hash
    ))).scalar_one_or_none()
    if document is None:
        await session.execute(delete(KnowledgeChunkModel).where(
            KnowledgeChunkModel.doc_hash == doc_hash
        ))
        await session.execute(delete(RetrievalCacheModel))
        return False

    fact_ids = list((await session.execute(select(BrainFactModel.id).where(
        BrainFactModel.source_document_id == document.id
    ))).scalars().all())
    if fact_ids:
        await session.execute(delete(BrainConflictModel).where(or_(
            BrainConflictModel.fact_a_id.in_(fact_ids),
            BrainConflictModel.fact_b_id.in_(fact_ids),
        )))
        await session.execute(delete(BrainRelationshipModel).where(
            BrainRelationshipModel.source_fact_id.in_(fact_ids)
        ))
        await session.execute(
            BrainFactModel.__table__.update().where(
                BrainFactModel.supersedes_fact_id.in_(fact_ids)
            ).values(supersedes_fact_id=None)
        )
        await session.execute(delete(BrainFactModel).where(
            BrainFactModel.id.in_(fact_ids)
        ))
    await session.execute(delete(KnowledgeCollectionDocumentModel).where(
        KnowledgeCollectionDocumentModel.document_id == document.id
    ))
    await session.execute(delete(KnowledgeChunkModel).where(or_(
        KnowledgeChunkModel.document_id == document.id,
        KnowledgeChunkModel.doc_hash == doc_hash,
    )))
    await session.delete(document)
    await session.execute(delete(RetrievalCacheModel))
    return True
