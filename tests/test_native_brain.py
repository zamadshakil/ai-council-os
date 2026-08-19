from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from src.core import brain, database as db, rag_engine
from src.core.jobs import JobService
from src.core.models import (
    WorkflowRunModel,
)
from src.core.retrieval_eval import run_retrieval_evaluation
from src.core.models import (
    BrainConflictModel,
    BrainEntityAliasModel,
    BrainEntityModel,
    BrainFactModel,
    BrainGapModel,
    BrainModelCallModel,
    BrainRelationshipModel,
    KnowledgeChunkModel,
    KnowledgeCollectionDocumentModel,
    KnowledgeCollectionModel,
    KnowledgeDocumentModel,
    LearningSuggestionModel,
    RetrievalCacheModel,
    SkillModel,
    SkillRevisionModel,
    TaskModel,
)
from src.worker import DurableWorker


def unit_vector(position: int = 0) -> list[float]:
    vector = [0.0] * rag_engine.EMBEDDING_DIM
    vector[position] = 1.0
    return vector


def test_chunk_spans_fusion_and_parent_diversity():
    text = "  Alpha evidence.\n\n" + ("Beta evidence sentence. " * 120)
    chunks = rag_engine._chunk_document_with_spans(text)
    assert chunks
    assert all(
        text[item["source_start"] : item["source_end"]] == item["text"]
        for item in chunks
    )

    fused = rag_engine._weighted_rrf(
        {"dense": ["a", "b"], "exact": ["b", "a"]},
        {"dense": 1.0, "exact": 2.0},
        k=0,
    )
    assert fused["b"] > fused["a"]

    candidates = [
        {
            "id": "a",
            "parent_key": "same",
            "vector": unit_vector(0),
            "fusion_score": 1.0,
        },
        {
            "id": "b",
            "parent_key": "same",
            "vector": unit_vector(0),
            "fusion_score": 0.9,
        },
        {
            "id": "c",
            "parent_key": "different",
            "vector": unit_vector(1),
            "fusion_score": 0.8,
        },
    ]
    selected = rag_engine._mmr(candidates, unit_vector(0), top_k=3)
    assert [item["id"] for item in selected] == ["a", "c"]


def test_local_schema_validation_checks_every_native_brain_column():
    missing = db.missing_sqlite_columns(
        {
            "tasks": {"version"},
            "knowledge_documents": {"raw_content"},
            "knowledge_chunks": {"document_id"},
        }
    )
    assert "metadata_json" in missing["knowledge_documents"]
    assert "embedding_model" in missing["knowledge_chunks"]
    assert "tasks" not in missing


@pytest.mark.asyncio
async def test_empty_collection_scope_never_falls_back_to_whole_library(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(
        rag_engine, "get_embedding", lambda _: _async_value(unit_vector())
    )
    monkeypatch.setattr(
        rag_engine, "_rerank", lambda _query, items: _async_value((items, []))
    )
    content = "Private product evidence belongs outside the selected empty collection."
    digest = hashlib.sha256(content.encode()).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="private.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content.encode(),
            normalized_text=content,
            status="ready",
            indexing_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
        )
        collection = KnowledgeCollectionModel(name="Empty scope")
        session.add_all([document, collection])
        await session.flush()
        session.add(
            KnowledgeChunkModel(
                document_id=document.id,
                doc_hash=digest,
                doc_name=document.filename,
                chunk_index=0,
                text=content,
                parent_text=content,
                source_start=0,
                source_end=len(content),
                parent_key="p0",
                index_version=rag_engine.INDEX_VERSION,
                embedding_model=rag_engine.EMBEDDING_MODEL,
                vector=unit_vector(),
            )
        )
        await session.commit()
        collection_id = collection.id

    response = await rag_engine.search_knowledge(
        "product evidence",
        collection_ids=[collection_id],
        top_k=5,
    )
    assert response["results"] == []
    assert response["scope"]["collection_ids"] == [collection_id]


@pytest.mark.asyncio
async def test_graph_candidates_expand_one_verified_relationship_hop(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    content = "Neighbor evidence is grounded in this exact source span."
    proposed_content = (
        "Unreviewed graph evidence must never influence a production run."
    )
    digest = hashlib.sha256(content.encode()).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="graph.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content.encode(),
            normalized_text=content,
            status="ready",
            indexing_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
        )
        proposed_document = KnowledgeDocumentModel(
            filename="proposed.md",
            content_type="text/markdown",
            size_bytes=len(proposed_content),
            sha256=hashlib.sha256(proposed_content.encode()).hexdigest(),
            storage_key=hashlib.sha256(proposed_content.encode()).hexdigest(),
            raw_content=proposed_content.encode(),
            normalized_text=proposed_content,
            status="ready",
            indexing_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
        )
        source = BrainEntityModel(
            name="Alpha",
            canonical_key="alpha",
            entity_type="project",
            status="verified",
            confidence=1,
        )
        neighbor = BrainEntityModel(
            name="Beta",
            canonical_key="beta",
            entity_type="product",
            status="verified",
            confidence=1,
        )
        session.add_all([document, proposed_document, source, neighbor])
        await session.flush()
        chunk = KnowledgeChunkModel(
            document_id=document.id,
            doc_hash=digest,
            doc_name=document.filename,
            chunk_index=0,
            text=content,
            parent_text=content,
            source_start=0,
            source_end=len(content),
            parent_key="p0",
            index_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
            vector=unit_vector(1),
        )
        proposed_chunk = KnowledgeChunkModel(
            document_id=proposed_document.id,
            doc_hash=proposed_document.sha256,
            doc_name=proposed_document.filename,
            chunk_index=0,
            text=proposed_content,
            parent_text=proposed_content,
            source_start=0,
            source_end=len(proposed_content),
            parent_key="p0",
            index_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
            vector=unit_vector(2),
        )
        session.add_all([chunk, proposed_chunk])
        await session.flush()
        fact = BrainFactModel(
            subject_entity_id=neighbor.id,
            predicate="evidence",
            value_text="grounded",
            normalized_value="grounded",
            status="verified",
            confidence=1,
            source_document_id=document.id,
            source_chunk_id=chunk.id,
            citation_text="Neighbor evidence",
        )
        proposed_fact = BrainFactModel(
            subject_entity_id=neighbor.id,
            predicate="unreviewed",
            value_text="must not appear",
            normalized_value="must not appear",
            status="proposed",
            confidence=1,
            source_document_id=proposed_document.id,
            source_chunk_id=proposed_chunk.id,
            citation_text="Unreviewed graph evidence",
        )
        session.add_all([fact, proposed_fact])
        await session.flush()
        session.add_all(
            [
                BrainEntityAliasModel(
                    entity_id=source.id, alias="Alpha", normalized_alias="alpha"
                ),
                BrainRelationshipModel(
                    source_entity_id=source.id,
                    target_entity_id=neighbor.id,
                    relationship_type="uses",
                    source_fact_id=fact.id,
                    status="verified",
                    confidence=1,
                ),
            ]
        )
        await session.commit()

    items, rankings = await rag_engine._candidate_sets(
        "Tell me about alpha",
        unit_vector(0),
        [],
        True,
    )
    assert chunk.id in rankings["graph"]
    assert proposed_chunk.id not in rankings["graph"]
    assert items[chunk.id]["fact_versions"] == [{"id": fact.id, "version": 1}]


@pytest.mark.asyncio
async def test_ingestion_is_restart_safe_and_does_not_duplicate_chunks(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(
        rag_engine,
        "get_embeddings",
        lambda texts: _async_value([unit_vector(i % 2) for i, _ in enumerate(texts)]),
    )
    monkeypatch.setattr(
        brain, "extract_document_graph", lambda _document_id: _async_value({"facts": 0})
    )
    content = ("Durable indexed passage. " * 90).encode()
    digest = hashlib.sha256(content).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="source.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content,
            status="pending",
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        document_id = document.id

    first = await rag_engine.ingest_pending_document(document_id)
    second = await rag_engine.ingest_pending_document(document_id)
    async with session_factory() as session:
        count = int(
            await session.scalar(select(func.count(KnowledgeChunkModel.id))) or 0
        )
    assert first["chunks_indexed"] == count > 0
    assert second["recovered"] is True
    assert second["chunks_indexed"] == count


@pytest.mark.asyncio
async def test_failed_graph_extraction_retries_without_reembedding(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    embedding_calls = 0
    graph_calls = 0

    async def embeddings(texts):
        nonlocal embedding_calls
        embedding_calls += 1
        return [unit_vector(index % 2) for index, _ in enumerate(texts)]

    async def flaky_graph(_document_id):
        nonlocal graph_calls
        graph_calls += 1
        if graph_calls == 1:
            raise RuntimeError("temporary graph provider outage")
        return {"facts": 0}

    monkeypatch.setattr(rag_engine, "get_embeddings", embeddings)
    monkeypatch.setattr(brain, "extract_document_graph", flaky_graph)
    content = ("Restart-safe graph evidence. " * 60).encode()
    digest = hashlib.sha256(content).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="retry.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content,
            status="pending",
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        document_id = document.id

    with pytest.raises(RuntimeError, match="Graph extraction failed"):
        await rag_engine.ingest_pending_document(document_id)
    async with session_factory() as session:
        failed = await session.get(KnowledgeDocumentModel, document_id)
        first_count = int(
            await session.scalar(select(func.count(KnowledgeChunkModel.id))) or 0
        )
        assert failed.status == "ready"
        assert failed.metadata_json["graph_status"] == "failed"
        assert "will be retried" in failed.warning

    recovered = await rag_engine.ingest_pending_document(document_id)
    async with session_factory() as session:
        ready = await session.get(KnowledgeDocumentModel, document_id)
        second_count = int(
            await session.scalar(select(func.count(KnowledgeChunkModel.id))) or 0
        )
        assert ready.metadata_json["graph_status"] == "ready"
        assert "Graph extraction failed" not in ready.warning
    assert recovered["recovered"] is True
    assert first_count == second_count > 0
    assert embedding_calls == 1
    assert graph_calls == 2


@pytest.mark.asyncio
async def test_nightly_maintenance_requeues_failed_graph_extraction(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(
        brain,
        "run_maintenance",
        lambda _date: _async_value({"status": "completed"}),
    )
    content = b"Current vectors with a temporarily failed graph extraction."
    digest = hashlib.sha256(content).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="graph-recovery.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content,
            normalized_text=content.decode(),
            status="ready",
            indexing_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
            metadata_json={"graph_status": "failed"},
        )
        session.add(document)
        await session.commit()
        await session.refresh(document)
        document_id = document.id

    jobs = JobService(session_factory=session_factory)
    worker = DurableWorker(worker_id="brain-recovery-test", job_service=jobs)
    result = await worker._maintain_brain({"maintenance_date": "2099-04-05"}, None)
    async with session_factory() as session:
        document = await session.get(KnowledgeDocumentModel, document_id)
        job = (
            await session.execute(
                select(WorkflowRunModel).where(
                    WorkflowRunModel.idempotency_key
                    == f"knowledge.graph-recovery:{document_id}:2099-04-05"
                )
            )
        ).scalar_one()
        assert document.ingestion_job_id == job.id
    assert result["graph_recovery_jobs_queued"] == 1
    assert result["reindex_jobs_queued"] == 0


@pytest.mark.asyncio
async def test_sqlite_cache_accepts_naive_expiry_from_database(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    embedding_calls = 0

    async def embedding(_query):
        nonlocal embedding_calls
        embedding_calls += 1
        return unit_vector()

    monkeypatch.setattr(rag_engine, "get_embedding", embedding)
    monkeypatch.setattr(
        rag_engine, "_rerank", lambda _query, items: _async_value((items, []))
    )
    content = "A stable cited passage for cached retrieval."
    digest = hashlib.sha256(content.encode()).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="cache.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content.encode(),
            normalized_text=content,
            status="ready",
            indexing_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
        )
        session.add(document)
        await session.flush()
        session.add(
            KnowledgeChunkModel(
                document_id=document.id,
                doc_hash=digest,
                doc_name=document.filename,
                chunk_index=0,
                text=content,
                parent_text=content,
                source_start=0,
                source_end=len(content),
                parent_key="p0",
                index_version=rag_engine.INDEX_VERSION,
                embedding_model=rag_engine.EMBEDDING_MODEL,
                vector=unit_vector(),
            )
        )
        await session.commit()

    first = await rag_engine.search_knowledge("stable cited passage")
    second = await rag_engine.search_knowledge("stable cited passage")
    assert first["cached"] is False
    assert second["cached"] is True
    assert embedding_calls == 1


@pytest.mark.asyncio
async def test_document_delete_removes_provenance_and_cache_without_orphans(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    content = "Source-backed fact and relationship."
    digest = hashlib.sha256(content.encode()).hexdigest()
    async with session_factory() as session:
        document = KnowledgeDocumentModel(
            filename="delete.md",
            content_type="text/markdown",
            size_bytes=len(content),
            sha256=digest,
            storage_key=digest,
            raw_content=content.encode(),
            normalized_text=content,
            status="ready",
            indexing_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
        )
        collection = KnowledgeCollectionModel(name="Delete scope")
        source = BrainEntityModel(
            name="Source", canonical_key="source", entity_type="project"
        )
        target = BrainEntityModel(
            name="Target", canonical_key="target", entity_type="product"
        )
        session.add_all([document, collection, source, target])
        await session.flush()
        chunk = KnowledgeChunkModel(
            document_id=document.id,
            doc_hash=digest,
            doc_name=document.filename,
            chunk_index=0,
            text=content,
            parent_text=content,
            source_start=0,
            source_end=len(content),
            parent_key="p0",
            index_version=rag_engine.INDEX_VERSION,
            embedding_model=rag_engine.EMBEDDING_MODEL,
            vector=unit_vector(),
        )
        session.add(chunk)
        await session.flush()
        fact_a = BrainFactModel(
            subject_entity_id=source.id,
            predicate="uses",
            value_text="Target",
            normalized_value="target",
            source_document_id=document.id,
            source_chunk_id=chunk.id,
            citation_text="Source-backed fact",
        )
        fact_b = BrainFactModel(
            subject_entity_id=source.id,
            predicate="uses",
            value_text="Other",
            normalized_value="other",
            source_document_id=document.id,
            source_chunk_id=chunk.id,
            citation_text="relationship",
        )
        session.add_all([fact_a, fact_b])
        await session.flush()
        session.add_all(
            [
                KnowledgeCollectionDocumentModel(
                    collection_id=collection.id, document_id=document.id
                ),
                BrainRelationshipModel(
                    source_entity_id=source.id,
                    target_entity_id=target.id,
                    relationship_type="uses",
                    source_fact_id=fact_a.id,
                ),
                BrainConflictModel(
                    fact_a_id=fact_a.id, fact_b_id=fact_b.id, reason="conflict"
                ),
                RetrievalCacheModel(
                    id="a" * 64,
                    query_hash="b" * 64,
                    scope_hash="c" * 64,
                    model_version=rag_engine.EMBEDDING_MODEL,
                    index_version=rag_engine.INDEX_VERSION,
                    query_vector=unit_vector(),
                    result={},
                    # Deliberately naive to mirror SQLite's storage behavior.
                    expires_at=datetime.now() + timedelta(minutes=5),
                ),
            ]
        )
        await session.commit()

    assert await rag_engine.delete_document(digest) is True
    async with session_factory() as session:
        for model in (
            KnowledgeDocumentModel,
            KnowledgeChunkModel,
            KnowledgeCollectionDocumentModel,
            BrainFactModel,
            BrainRelationshipModel,
            BrainConflictModel,
            RetrievalCacheModel,
        ):
            assert (
                int(await session.scalar(select(func.count()).select_from(model)) or 0)
                == 0
            )


@pytest.mark.asyncio
async def test_maintenance_detects_conflict_gap_and_never_verifies(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(
        brain,
        "_structured_call_with_cache",
        lambda **_: _async_value((brain.MaintenanceAnalysis(), {"cost_usd": 0})),
    )
    async with session_factory() as session:
        entity = BrainEntityModel(
            name="Project",
            canonical_key="project",
            entity_type="project",
            status="proposed",
            confidence=0.9,
        )
        session.add(entity)
        await session.flush()
        session.add_all(
            [
                BrainFactModel(
                    subject_entity_id=entity.id,
                    predicate="budget",
                    value_text="10",
                    normalized_value="10",
                    status="proposed",
                    confidence=0.9,
                ),
                BrainFactModel(
                    subject_entity_id=entity.id,
                    predicate="budget",
                    value_text="20",
                    normalized_value="20",
                    status="proposed",
                    confidence=0.9,
                ),
            ]
        )
        await session.commit()

    result = await brain.run_maintenance("2099-01-01")
    recovered = await brain.run_maintenance("2099-01-01")
    async with session_factory() as session:
        facts = (await session.execute(select(BrainFactModel))).scalars().all()
        conflicts = int(
            await session.scalar(select(func.count(BrainConflictModel.id))) or 0
        )
        gaps = int(await session.scalar(select(func.count(BrainGapModel.id))) or 0)
    assert result["conflicts_created"] == conflicts == 1
    assert gaps >= 2
    assert all(fact.status == "proposed" for fact in facts)
    assert recovered["recovered"] is True
    assert recovered["conflicts_created"] == 1


@pytest.mark.asyncio
async def test_persisted_structured_call_prevents_duplicate_model_charge(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    async with session_factory() as session:
        session.add(
            BrainModelCallModel(
                purpose="brain_maintenance_analysis",
                resource_type="maintenance_date",
                resource_id="2099-02-01",
                prompt="persisted prompt",
                model_id="google/gemini-3.7-flash",
                structured_output={"contradictions": [], "gaps": []},
                input_tokens=12,
                output_tokens=4,
                cost_usd=0.001,
                error="",
            )
        )
        await session.commit()

    async def must_not_call_provider(**_: object):
        raise AssertionError(
            "provider should not be charged after a persisted successful call"
        )

    monkeypatch.setattr(brain, "call_llm_structured", must_not_call_provider)
    parsed, metrics = await brain._structured_call_with_cache(
        purpose="brain_maintenance_analysis",
        resource_type="maintenance_date",
        resource_id="2099-02-01",
        prompt="persisted prompt",
        output_model=brain.MaintenanceAnalysis,
        max_tokens=100,
    )
    assert parsed == brain.MaintenanceAnalysis()
    assert metrics["recovered"] is True
    assert metrics["cost_usd"] == 0.001


@pytest.mark.asyncio
async def test_only_active_approved_skill_revision_can_influence_run(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(
        rag_engine, "get_embedding", lambda _: _async_value(unit_vector())
    )
    async with session_factory() as session:
        skill = SkillModel(
            name="Voice", scope_type="council", scope_id="content", tags=["voice"]
        )
        session.add(skill)
        await session.flush()
        active = SkillRevisionModel(
            skill_id=skill.id,
            revision_number=1,
            instructions="Use concise brand language.",
            token_count=6,
            vector=unit_vector(),
            evidence={"approved": True},
        )
        inactive = SkillRevisionModel(
            skill_id=skill.id,
            revision_number=2,
            instructions="Unapproved replacement.",
            token_count=4,
            vector=unit_vector(),
            evidence={"approved": False},
        )
        session.add_all([active, inactive])
        await session.flush()
        skill.active_revision_id = active.id
        await session.commit()

    selected = await brain.select_skills(
        council="content", query="brand voice", token_budget=6
    )
    assert [item["revision_id"] for item in selected] == [active.id]
    assert (
        await brain.select_skills(
            council="content", query="brand voice", token_budget=5
        )
    ) == []


@pytest.mark.asyncio
async def test_learning_suggestion_requires_admin_activation(
    session_factory, monkeypatch
):
    monkeypatch.setattr(db, "async_session", session_factory)
    monkeypatch.setattr(
        rag_engine, "get_embedding", lambda _: _async_value(unit_vector())
    )
    async with session_factory() as session:
        task = TaskModel(
            task_id="learning-task",
            council="sales",
            status="approved",
            task_description="Draft",
        )
        session.add(task)
        await session.flush()
        suggestion = LearningSuggestionModel(
            source_task_id=task.task_id,
            scope_type="council",
            scope_id="sales",
            title="CTA rule",
            rationale="Administrator consistently corrected CTA placement.",
            proposed_instructions="Put one clear CTA in the final sentence.",
            idempotency_key="learning:learning-task",
            status="pending",
            version=1,
        )
        session.add(suggestion)
        await session.commit()
        await session.refresh(suggestion)
        suggestion_id = suggestion.id

    before = await brain.select_skills(council="sales", query="CTA", token_budget=100)
    activated = await brain.activate_learning_suggestion(suggestion_id, 1)
    after = await brain.select_skills(council="sales", query="CTA", token_budget=100)
    assert before == []
    assert after[0]["revision_id"] == activated["revision_id"]


@pytest.mark.asyncio
async def test_retrieval_evaluation_reports_precision_citations_latency_and_delta():
    async def fake_search(query: str, **_: object) -> dict:
        return {
            "results": [
                {
                    "doc_hash": "expected",
                    "source_start": 2,
                    "source_end": 12,
                    "citation": "source.md · characters 3–12",
                }
            ],
            "warnings": [],
        }

    result = await run_retrieval_evaluation(
        {
            "version": "fixture-v1",
            "baseline_metrics": {"precision_at_k": 0.5, "citation_correctness": 0.5},
            "cases": [
                {
                    "id": "fixture",
                    "query": "supported claim",
                    "expected_document_hashes": ["expected"],
                    "top_k": 1,
                }
            ],
        },
        search_fn=fake_search,
        persist=False,
    )

    assert result["metrics"]["precision_at_k"] == 1.0
    assert result["metrics"]["citation_correctness"] == 1.0
    assert result["metrics"]["delta"]["precision_at_k"] == 0.5
    assert result["metrics"]["provider_cost_usd"] == 0.0


async def _async_value(value):
    return value
