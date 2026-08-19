"""Council Brain graph, human-reviewed skills, and learning services."""

from __future__ import annotations

import difflib
import hashlib
import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, func, or_, select

from src.core import database as db
from src.core.llm_router import BRAIN_MODEL, call_llm_structured
from src.core.models import (
    ApprovalModel,
    BrainConflictModel,
    BrainEntityAliasModel,
    BrainEntityModel,
    BrainFactModel,
    BrainGapModel,
    BrainMaintenanceRunModel,
    BrainModelCallModel,
    BrainRelationshipModel,
    CouncilRunModel,
    KnowledgeChunkModel,
    KnowledgeDocumentModel,
    LearningSuggestionModel,
    RetrievalCacheModel,
    SkillModel,
    SkillRevisionModel,
    TaskModel,
    utcnow,
)


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=240)
    entity_type: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list, max_length=12)
    description: str = Field(default="", max_length=1000)
    confidence: float = Field(ge=0, le=1)


class ExtractedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=240)
    predicate: str = Field(min_length=1, max_length=180)
    value: str = Field(min_length=1, max_length=3000)
    citation: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    effective_from: datetime | None = None
    effective_to: datetime | None = None


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: str = Field(min_length=1, max_length=240)
    relationship_type: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=240)
    citation: str = Field(min_length=1, max_length=1000)
    confidence: float = Field(ge=0, le=1)


class GraphExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entities: list[ExtractedEntity] = Field(default_factory=list, max_length=80)
    facts: list[ExtractedFact] = Field(default_factory=list, max_length=150)
    relationships: list[ExtractedRelationship] = Field(
        default_factory=list, max_length=100
    )


class LearningExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reusable: bool
    title: str = Field(default="", max_length=200)
    rationale: str = Field(default="", max_length=2000)
    instructions: str = Field(default="", max_length=6000)
    tags: list[str] = Field(default_factory=list, max_length=12)


class ContradictionFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fact_a_id: str
    fact_b_id: str
    reason: str = Field(min_length=1, max_length=2000)
    severity: Literal["low", "medium", "high"] = "medium"


class GapFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=2000)
    related_fact_ids: list[str] = Field(default_factory=list, max_length=20)


class MaintenanceAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contradictions: list[ContradictionFinding] = Field(
        default_factory=list, max_length=100
    )
    gaps: list[GapFinding] = Field(default_factory=list, max_length=100)


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _tokens(value: str) -> int:
    return max(1, (len(value) + 3) // 4)


async def _record_model_call(
    *,
    purpose: str,
    resource_type: str,
    resource_id: str,
    prompt: str,
    output: dict[str, Any] | None = None,
    metrics: dict[str, Any] | None = None,
    error: str = "",
) -> None:
    metrics = metrics or {}
    async with db.async_session() as session:
        session.add(
            BrainModelCallModel(
                purpose=purpose,
                resource_type=resource_type,
                resource_id=resource_id,
                prompt=prompt,
                model_id=BRAIN_MODEL,
                structured_output=output or {},
                input_tokens=int(metrics.get("input_tokens") or 0),
                output_tokens=int(metrics.get("output_tokens") or 0),
                cost_usd=metrics.get("cost_usd"),
                error=error[:8000],
            )
        )
        await session.commit()


async def _structured_call_with_cache(
    *,
    purpose: str,
    resource_type: str,
    resource_id: str,
    prompt: str,
    output_model: type[BaseModel],
    max_tokens: int,
) -> tuple[BaseModel, dict[str, Any]]:
    """Reuse a persisted successful structured output after a worker restart."""
    async with db.async_session() as session:
        prior = (
            await session.execute(
                select(BrainModelCallModel)
                .where(
                    BrainModelCallModel.purpose == purpose,
                    BrainModelCallModel.resource_type == resource_type,
                    BrainModelCallModel.resource_id == resource_id,
                    BrainModelCallModel.model_id == BRAIN_MODEL,
                    BrainModelCallModel.prompt == prompt,
                    BrainModelCallModel.error == "",
                )
                .order_by(BrainModelCallModel.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if prior and prior.structured_output:
        return output_model.model_validate(prior.structured_output), {
            "input_tokens": prior.input_tokens,
            "output_tokens": prior.output_tokens,
            "cost_usd": prior.cost_usd,
            "recovered": True,
        }
    try:
        parsed, metrics = await call_llm_structured(
            messages=[
                {
                    "role": "system",
                    "content": "You are the Council Brain structured intelligence engine.",
                },
                {"role": "user", "content": prompt},
            ],
            model_id=BRAIN_MODEL,
            output_model=output_model,
            temperature=0.0,
            max_tokens=max_tokens,
        )
        await _record_model_call(
            purpose=purpose,
            resource_type=resource_type,
            resource_id=resource_id,
            prompt=prompt,
            output=parsed.model_dump(),
            metrics=metrics,
        )
        return parsed, metrics
    except Exception as exc:
        await _record_model_call(
            purpose=purpose,
            resource_type=resource_type,
            resource_id=resource_id,
            prompt=prompt,
            error=str(exc),
        )
        raise


async def extract_document_graph(document_id: str) -> dict[str, int]:
    """Extract proposed, provenance-backed graph records from one ready document."""
    async with db.async_session() as session:
        document = await session.get(KnowledgeDocumentModel, document_id)
        if not document or document.status != "ready":
            raise ValueError(
                "Only a ready document can be extracted into the brain graph."
            )
        chunks = (
            (
                await session.execute(
                    select(KnowledgeChunkModel)
                    .where(KnowledgeChunkModel.document_id == document_id)
                    .order_by(KnowledgeChunkModel.chunk_index)
                )
            )
            .scalars()
            .all()
        )
        source = document.normalized_text[:60000]
    prompt = (
        "Extract only explicitly supported entities, atomic facts, and relationships. "
        "Every fact must contain a short verbatim citation appearing in the source. "
        "Include effective_from/effective_to only when the source explicitly states the dates. "
        "Do not infer or fill gaps. Uploaded-document facts are proposals, never verified.\n\n"
        f"SOURCE ({document.filename}):\n{source}"
    )
    parsed, _ = await _structured_call_with_cache(
        purpose="document_graph_extraction",
        resource_type="knowledge_document",
        resource_id=document_id,
        prompt=prompt,
        output_model=GraphExtraction,
        max_tokens=7000,
    )

    def citation_chunk(citation: str) -> KnowledgeChunkModel | None:
        exact = citation.strip()
        return next(
            (chunk for chunk in chunks if exact and exact in chunk.parent_text), None
        )

    entity_ids: dict[str, str] = {}
    async with db.async_session() as session:
        for candidate in parsed.entities:
            canonical = _key(candidate.name)
            entity = (
                await session.execute(
                    select(BrainEntityModel).where(
                        BrainEntityModel.entity_type == _key(candidate.entity_type),
                        BrainEntityModel.canonical_key == canonical,
                    )
                )
            ).scalar_one_or_none()
            if entity is None:
                entity = BrainEntityModel(
                    name=candidate.name,
                    canonical_key=canonical,
                    entity_type=_key(candidate.entity_type),
                    description=candidate.description,
                    confidence=candidate.confidence,
                    status="proposed",
                )
                session.add(entity)
                await session.flush()
            entity_ids[canonical] = entity.id
            for alias in {candidate.name, *candidate.aliases}:
                normalized = _key(alias)
                exists = await session.scalar(
                    select(func.count(BrainEntityAliasModel.id)).where(
                        BrainEntityAliasModel.entity_id == entity.id,
                        BrainEntityAliasModel.normalized_alias == normalized,
                    )
                )
                if not exists and normalized:
                    session.add(
                        BrainEntityAliasModel(
                            entity_id=entity.id,
                            alias=alias,
                            normalized_alias=normalized,
                        )
                    )
        await session.flush()
        facts_created = 0
        fact_by_signature: dict[tuple[str, str, str], str] = {}
        for candidate in parsed.facts:
            subject_id = entity_ids.get(_key(candidate.subject))
            chunk = citation_chunk(candidate.citation)
            status_reason = (
                ""
                if chunk and candidate.confidence >= 0.85
                else (
                    "Citation could not be validated."
                    if not chunk
                    else "Low extraction confidence."
                )
            )
            signature = (
                subject_id or "",
                _key(candidate.predicate),
                _key(candidate.value),
            )
            existing = (
                await session.execute(
                    select(BrainFactModel).where(
                        BrainFactModel.subject_entity_id == subject_id,
                        BrainFactModel.predicate == signature[1],
                        BrainFactModel.normalized_value == signature[2],
                        BrainFactModel.source_document_id == document_id,
                    )
                )
            ).scalar_one_or_none()
            if existing is None:
                existing = BrainFactModel(
                    subject_entity_id=subject_id,
                    predicate=signature[1],
                    value_text=candidate.value,
                    normalized_value=signature[2],
                    status="proposed",
                    confidence=candidate.confidence,
                    source_document_id=document_id,
                    source_chunk_id=chunk.id if chunk else None,
                    citation_text=candidate.citation,
                    review_reason=status_reason,
                    effective_from=candidate.effective_from,
                    effective_to=candidate.effective_to,
                )
                session.add(existing)
                await session.flush()
                facts_created += 1
            fact_by_signature[signature] = existing.id
        relationships_created = 0
        for candidate in parsed.relationships:
            source_id, target_id = (
                entity_ids.get(_key(candidate.source)),
                entity_ids.get(_key(candidate.target)),
            )
            if not source_id or not target_id:
                continue
            chunk = citation_chunk(candidate.citation)
            if chunk is None:
                continue
            fact_signature = (
                source_id,
                _key(candidate.relationship_type),
                _key(candidate.target),
            )
            source_fact_id = fact_by_signature.get(fact_signature)
            if source_fact_id is None:
                relation_fact = BrainFactModel(
                    subject_entity_id=source_id,
                    predicate=fact_signature[1],
                    value_text=candidate.target,
                    normalized_value=fact_signature[2],
                    status="proposed",
                    confidence=candidate.confidence,
                    source_document_id=document_id,
                    source_chunk_id=chunk.id,
                    citation_text=candidate.citation,
                    review_reason="Relationship fact requires administrator verification.",
                )
                session.add(relation_fact)
                await session.flush()
                source_fact_id = relation_fact.id
                fact_by_signature[fact_signature] = relation_fact.id
                facts_created += 1
            exists = await session.scalar(
                select(func.count(BrainRelationshipModel.id)).where(
                    BrainRelationshipModel.source_entity_id == source_id,
                    BrainRelationshipModel.target_entity_id == target_id,
                    BrainRelationshipModel.relationship_type
                    == _key(candidate.relationship_type),
                )
            )
            if not exists:
                session.add(
                    BrainRelationshipModel(
                        source_entity_id=source_id,
                        target_entity_id=target_id,
                        relationship_type=_key(candidate.relationship_type),
                        source_fact_id=source_fact_id,
                        confidence=candidate.confidence,
                        status="proposed",
                    )
                )
                relationships_created += 1
        await session.commit()
    return {
        "entities": len(entity_ids),
        "facts": facts_created,
        "relationships": relationships_created,
    }


async def run_maintenance(maintenance_date: str | None = None) -> dict[str, Any]:
    """Detect deterministic conflicts/gaps without approving or external actions."""
    maintenance_date = maintenance_date or date.today().isoformat()
    async with db.async_session() as session:
        run = (
            await session.execute(
                select(BrainMaintenanceRunModel).where(
                    BrainMaintenanceRunModel.maintenance_date == maintenance_date
                )
            )
        ).scalar_one_or_none()
        if run and run.status == "completed":
            return {**(run.result or {}), "recovered": True}
        if run is None:
            run = BrainMaintenanceRunModel(
                maintenance_date=maintenance_date, status="running"
            )
            session.add(run)
        else:
            run.status, run.error, run.version = "running", "", run.version + 1
        await session.commit()
        await session.refresh(run)
        run_id = run.id
    try:
        conflicts_created = gaps_created = citations_repaired = 0
        async with db.async_session() as session:
            analysis_facts = (
                (
                    await session.execute(
                        select(BrainFactModel)
                        .where(BrainFactModel.status.in_(("proposed", "verified")))
                        .order_by(BrainFactModel.id)
                        .limit(600)
                    )
                )
                .scalars()
                .all()
            )
        analysis: MaintenanceAnalysis = MaintenanceAnalysis()
        if analysis_facts:
            fact_payload = [
                {
                    "id": fact.id,
                    "subject_entity_id": fact.subject_entity_id,
                    "predicate": fact.predicate,
                    "value": fact.value_text,
                    "status": fact.status,
                    "citation": fact.citation_text,
                }
                for fact in analysis_facts
            ]
            prompt = (
                "Review these provenance-backed facts for genuine semantic contradictions and "
                "important missing-evidence questions. Reference only provided fact IDs. Do not "
                "approve, reject, correct, or invent facts.\n\nFACTS:\n"
                + json.dumps(fact_payload, ensure_ascii=False, sort_keys=True)
            )
            parsed, _ = await _structured_call_with_cache(
                purpose="brain_maintenance_analysis",
                resource_type="maintenance_date",
                resource_id=maintenance_date,
                prompt=prompt,
                output_model=MaintenanceAnalysis,
                max_tokens=5000,
            )
            analysis = MaintenanceAnalysis.model_validate(parsed.model_dump())
        async with db.async_session() as session:
            facts = (
                (
                    await session.execute(
                        select(BrainFactModel).where(
                            BrainFactModel.status.in_(("proposed", "verified"))
                        )
                    )
                )
                .scalars()
                .all()
            )
            fact_map = {fact.id: fact for fact in facts}
            citation_doc_ids = {
                fact.source_document_id
                for fact in facts
                if fact.source_document_id
                and fact.citation_text
                and not fact.source_chunk_id
            }
            citation_chunks = (
                (
                    await session.execute(
                        select(KnowledgeChunkModel).where(
                            KnowledgeChunkModel.document_id.in_(citation_doc_ids)
                        )
                    )
                )
                .scalars()
                .all()
                if citation_doc_ids
                else []
            )
            chunks_by_document: dict[str, list[KnowledgeChunkModel]] = {}
            for chunk in citation_chunks:
                chunks_by_document.setdefault(str(chunk.document_id), []).append(chunk)
            grouped: dict[tuple[str, str], list[BrainFactModel]] = {}
            duplicate_groups: dict[tuple[str, str, str], list[BrainFactModel]] = {}
            for fact in facts:
                grouped.setdefault(
                    (fact.subject_entity_id or "", fact.predicate), []
                ).append(fact)
                duplicate_groups.setdefault(
                    (
                        fact.subject_entity_id or "",
                        fact.predicate,
                        fact.normalized_value,
                    ),
                    [],
                ).append(fact)
                if not fact.source_document_id and not fact.approval_id:
                    gap_key = hashlib.sha256(f"uncited:{fact.id}".encode()).hexdigest()
                    if not await session.scalar(
                        select(func.count(BrainGapModel.id)).where(
                            BrainGapModel.gap_key == gap_key
                        )
                    ):
                        session.add(
                            BrainGapModel(
                                gap_key=gap_key,
                                question=f"What primary evidence supports: {fact.predicate} = {fact.value_text}?",
                                context={
                                    "fact_id": fact.id,
                                    "reason": "missing_provenance",
                                },
                            )
                        )
                        gaps_created += 1
                if (
                    fact.effective_to
                    and fact.effective_to <= utcnow()
                    and fact.status == "verified"
                ):
                    gap_key = hashlib.sha256(
                        f"stale:{fact.id}:{fact.effective_to.isoformat()}".encode()
                    ).hexdigest()
                    if not await session.scalar(
                        select(func.count(BrainGapModel.id)).where(
                            BrainGapModel.gap_key == gap_key
                        )
                    ):
                        session.add(
                            BrainGapModel(
                                gap_key=gap_key,
                                question=f"Should expired fact '{fact.predicate}' be replaced with current evidence?",
                                context={"fact_id": fact.id, "reason": "stale_fact"},
                            )
                        )
                        gaps_created += 1
                if (
                    fact.source_document_id
                    and fact.citation_text
                    and not fact.source_chunk_id
                ):
                    normalized_citation = _key(fact.citation_text)
                    matching = next(
                        (
                            chunk
                            for chunk in chunks_by_document.get(
                                fact.source_document_id, []
                            )
                            if normalized_citation in _key(chunk.parent_text)
                        ),
                        None,
                    )
                    if matching:
                        fact.source_chunk_id = matching.id
                        fact.version += 1
                        citations_repaired += 1
            for duplicate_facts in duplicate_groups.values():
                if len(duplicate_facts) < 2:
                    continue
                duplicate_ids = sorted(fact.id for fact in duplicate_facts)
                gap_key = hashlib.sha256(
                    f"duplicate-facts:{','.join(duplicate_ids)}".encode()
                ).hexdigest()
                if not await session.scalar(
                    select(func.count(BrainGapModel.id)).where(
                        BrainGapModel.gap_key == gap_key
                    )
                ):
                    session.add(
                        BrainGapModel(
                            gap_key=gap_key,
                            question="Review and consolidate duplicate fact versions without deleting provenance.",
                            context={
                                "fact_ids": duplicate_ids,
                                "reason": "duplicate_facts",
                            },
                        )
                    )
                    gaps_created += 1
            aliases = (
                (await session.execute(select(BrainEntityAliasModel))).scalars().all()
            )
            aliases_by_key: dict[str, set[str]] = {}
            for alias in aliases:
                aliases_by_key.setdefault(alias.normalized_alias, set()).add(
                    alias.entity_id
                )
            for alias, entity_ids in aliases_by_key.items():
                if not alias or len(entity_ids) < 2:
                    continue
                ids = sorted(entity_ids)
                gap_key = hashlib.sha256(
                    f"duplicate-entities:{alias}:{','.join(ids)}".encode()
                ).hexdigest()
                if not await session.scalar(
                    select(func.count(BrainGapModel.id)).where(
                        BrainGapModel.gap_key == gap_key
                    )
                ):
                    session.add(
                        BrainGapModel(
                            gap_key=gap_key,
                            question=f"Do the entities sharing alias '{alias}' represent the same subject?",
                            context={
                                "entity_ids": ids,
                                "reason": "possible_duplicate_entities",
                            },
                        )
                    )
                    gaps_created += 1
            for candidate_facts in grouped.values():
                for left_index, left in enumerate(candidate_facts):
                    for right in candidate_facts[left_index + 1 :]:
                        if left.normalized_value == right.normalized_value:
                            continue
                        fact_a, fact_b = sorted((left.id, right.id))
                        exists = await session.scalar(
                            select(func.count(BrainConflictModel.id)).where(
                                BrainConflictModel.fact_a_id == fact_a,
                                BrainConflictModel.fact_b_id == fact_b,
                            )
                        )
                        if not exists:
                            session.add(
                                BrainConflictModel(
                                    fact_a_id=fact_a,
                                    fact_b_id=fact_b,
                                    reason="Facts share a subject and predicate but have different values.",
                                    severity="high"
                                    if left.status == right.status == "verified"
                                    else "medium",
                                )
                            )
                            conflicts_created += 1
            for finding in analysis.contradictions:
                left, right = (
                    fact_map.get(finding.fact_a_id),
                    fact_map.get(finding.fact_b_id),
                )
                if not left or not right or left.id == right.id:
                    continue
                fact_a, fact_b = sorted((left.id, right.id))
                exists = await session.scalar(
                    select(func.count(BrainConflictModel.id)).where(
                        BrainConflictModel.fact_a_id == fact_a,
                        BrainConflictModel.fact_b_id == fact_b,
                    )
                )
                if not exists:
                    session.add(
                        BrainConflictModel(
                            fact_a_id=fact_a,
                            fact_b_id=fact_b,
                            reason=finding.reason,
                            severity=finding.severity,
                        )
                    )
                    conflicts_created += 1
            for finding in analysis.gaps:
                valid_ids = sorted(
                    {
                        fact_id
                        for fact_id in finding.related_fact_ids
                        if fact_id in fact_map
                    }
                )
                gap_key = hashlib.sha256(
                    f"model:{finding.question}:{','.join(valid_ids)}".encode()
                ).hexdigest()
                exists = await session.scalar(
                    select(func.count(BrainGapModel.id)).where(
                        BrainGapModel.gap_key == gap_key
                    )
                )
                if not exists:
                    session.add(
                        BrainGapModel(
                            gap_key=gap_key,
                            question=finding.question,
                            context={
                                "fact_ids": valid_ids,
                                "reason": "model_detected_missing_evidence",
                            },
                        )
                    )
                    gaps_created += 1
            run = await session.get(BrainMaintenanceRunModel, run_id)
            result = {
                "conflicts_created": conflicts_created,
                "gaps_created": gaps_created,
                "citations_repaired": citations_repaired,
            }
            if run:
                run.status, run.result, run.version = (
                    "completed",
                    result,
                    run.version + 1,
                )
            await session.commit()
        return result
    except Exception as exc:
        async with db.async_session() as session:
            run = await session.get(BrainMaintenanceRunModel, run_id)
            if run:
                run.status, run.error, run.version = (
                    "failed",
                    str(exc)[:8000],
                    run.version + 1,
                )
                await session.commit()
        raise


async def create_learning_suggestion(task_id: str) -> dict[str, Any]:
    """Compare generated/final text and persist a reviewable procedural lesson."""
    idempotency_key = f"learning:{task_id}"
    async with db.async_session() as session:
        existing = (
            await session.execute(
                select(LearningSuggestionModel).where(
                    LearningSuggestionModel.idempotency_key == idempotency_key
                )
            )
        ).scalar_one_or_none()
        if existing:
            return {"id": existing.id, "status": existing.status, "recovered": True}
        task = await session.get(TaskModel, task_id)
        approval = (
            await session.execute(
                select(ApprovalModel).where(
                    ApprovalModel.resource_type == "task",
                    ApprovalModel.resource_id == task_id,
                )
            )
        ).scalar_one_or_none()
        if not task or not approval or approval.status != "approved":
            raise ValueError("Learning requires an approved task.")
        generated = str(
            (task.context or {}).get("generated_output") or task.final_output
        )
        final = str((approval.edited_output or {}).get("content") or task.final_output)
        council = task.council
    prompt = (
        "Compare the generated and administrator-approved text. Suggest one reusable procedural "
        "instruction only when the edit expresses a durable preference. Never turn factual content "
        "or one-off wording into a skill.\n\nGENERATED:\n"
        + generated[:25000]
        + "\n\nAPPROVED:\n"
        + final[:25000]
    )
    parsed, _ = await _structured_call_with_cache(
        purpose="learning_suggestion",
        resource_type="task",
        resource_id=task_id,
        prompt=prompt,
        output_model=LearningExtraction,
        max_tokens=1800,
    )
    if not parsed.reusable or not parsed.instructions.strip():
        return {"task_id": task_id, "status": "no_reusable_lesson"}
    diff = "\n".join(
        difflib.unified_diff(
            [],
            parsed.instructions.splitlines(),
            fromfile="current",
            tofile="proposed",
            lineterm="",
        )
    )
    async with db.async_session() as session:
        suggestion = LearningSuggestionModel(
            source_task_id=task_id,
            scope_type="council",
            scope_id=council,
            title=parsed.title or f"{council.title()} Council lesson",
            rationale=parsed.rationale,
            proposed_instructions=parsed.instructions,
            diff_text=diff,
            evidence={
                "task_id": task_id,
                "generated": generated[:4000],
                "approved": final[:4000],
                "tags": parsed.tags,
            },
            idempotency_key=idempotency_key,
        )
        session.add(suggestion)
        await session.commit()
        await session.refresh(suggestion)
    return {"id": suggestion.id, "status": suggestion.status}


async def extract_approved_task_graph(task_id: str) -> dict[str, int]:
    """Create versioned facts from an approved output with task/approval provenance."""
    async with db.async_session() as session:
        task = await session.get(TaskModel, task_id)
        approval = (
            await session.execute(
                select(ApprovalModel).where(
                    ApprovalModel.resource_type == "task",
                    ApprovalModel.resource_id == task_id,
                )
            )
        ).scalar_one_or_none()
        if not task or not approval or approval.status != "approved":
            raise ValueError("Approved task provenance is required.")
        content = task.final_output
        council_run = await session.scalar(
            select(CouncilRunModel.id)
            .where(CouncilRunModel.task_id == task_id)
            .order_by(CouncilRunModel.created_at.desc())
            .limit(1)
        )
    prompt = (
        "Extract only durable project/product/brand/audience/proposal facts explicitly present in "
        "this administrator-approved output. Every fact citation must be a short exact excerpt. "
        "Include effective_from/effective_to only when the output explicitly states the dates. "
        "Avoid procedural writing preferences; those belong to skills.\n\nAPPROVED OUTPUT:\n"
        + content[:60000]
    )
    parsed, _ = await _structured_call_with_cache(
        purpose="approved_output_graph",
        resource_type="task",
        resource_id=task_id,
        prompt=prompt,
        output_model=GraphExtraction,
        max_tokens=5000,
    )
    entity_ids: dict[str, str] = {}
    facts_created = 0
    async with db.async_session() as session:
        for candidate in parsed.entities:
            canonical, entity_type = _key(candidate.name), _key(candidate.entity_type)
            entity = (
                await session.execute(
                    select(BrainEntityModel).where(
                        BrainEntityModel.entity_type == entity_type,
                        BrainEntityModel.canonical_key == canonical,
                    )
                )
            ).scalar_one_or_none()
            if entity is None:
                entity = BrainEntityModel(
                    name=candidate.name,
                    canonical_key=canonical,
                    entity_type=entity_type,
                    description=candidate.description,
                    status="verified" if candidate.confidence >= 0.85 else "proposed",
                    confidence=candidate.confidence,
                )
                session.add(entity)
                await session.flush()
            entity_ids[canonical] = entity.id
            for alias in {candidate.name, *candidate.aliases}:
                normalized = _key(alias)
                exists = await session.scalar(
                    select(func.count(BrainEntityAliasModel.id)).where(
                        BrainEntityAliasModel.entity_id == entity.id,
                        BrainEntityAliasModel.normalized_alias == normalized,
                    )
                )
                if normalized and not exists:
                    session.add(
                        BrainEntityAliasModel(
                            entity_id=entity.id,
                            alias=alias,
                            normalized_alias=normalized,
                        )
                    )
        await session.flush()
        for candidate in parsed.facts:
            citation_valid = bool(
                candidate.citation.strip() and candidate.citation.strip() in content
            )
            status = (
                "verified"
                if citation_valid and candidate.confidence >= 0.85
                else "proposed"
            )
            normalized_value = _key(candidate.value)
            subject_id = entity_ids.get(_key(candidate.subject))
            exists = await session.scalar(
                select(func.count(BrainFactModel.id)).where(
                    BrainFactModel.subject_entity_id == subject_id,
                    BrainFactModel.predicate == _key(candidate.predicate),
                    BrainFactModel.normalized_value == normalized_value,
                    BrainFactModel.approval_id == approval.id,
                )
            )
            if not exists:
                session.add(
                    BrainFactModel(
                        subject_entity_id=subject_id,
                        predicate=_key(candidate.predicate),
                        value_text=candidate.value,
                        normalized_value=normalized_value,
                        status=status,
                        confidence=candidate.confidence,
                        council_run_id=council_run,
                        approval_id=approval.id,
                        citation_text=candidate.citation,
                        effective_from=candidate.effective_from,
                        effective_to=candidate.effective_to,
                        review_reason=""
                        if status == "verified"
                        else "Citation or confidence requires administrator review.",
                    )
                )
                facts_created += 1
        await session.commit()
    return {"entities": len(entity_ids), "facts": facts_created}


async def select_skills(
    *,
    council: str = "",
    workflow: str = "",
    integration: str = "",
    query: str,
    token_budget: int = 1200,
) -> list[dict[str, Any]]:
    """Select only active, administrator-approved immutable revisions."""
    from src.core.rag_engine import _cosine, get_embedding

    scopes = [("global", "")]
    if council:
        scopes.append(("council", council))
    if workflow:
        scopes.append(("workflow", workflow))
    if integration:
        scopes.append(("integration", integration))
    async with db.async_session() as session:
        skills = (
            (
                await session.execute(
                    select(SkillModel).where(
                        or_(
                            *[
                                and_(
                                    SkillModel.scope_type == scope_type,
                                    SkillModel.scope_id == scope_id,
                                )
                                for scope_type, scope_id in scopes
                            ]
                        )
                    )
                )
            )
            .scalars()
            .all()
        )
        pairs: list[tuple[SkillModel, SkillRevisionModel]] = []
        for skill in skills:
            if not skill.active_revision_id:
                continue
            revision = await session.get(SkillRevisionModel, skill.active_revision_id)
            if revision:
                pairs.append((skill, revision))
    if not pairs:
        return []
    query_vector = await get_embedding(query)
    query_terms = set(_key(query).split())
    ranked = sorted(
        pairs,
        key=lambda pair: (
            _cosine(query_vector, list(pair[1].vector or []))
            + 0.08 * len(query_terms & set(_key(" ".join(pair[0].tags or [])).split()))
        ),
        reverse=True,
    )
    selected, used = [], 0
    for skill, revision in ranked:
        tokens = revision.token_count or _tokens(revision.instructions)
        if used + tokens > max(0, token_budget):
            continue
        selected.append(
            {
                "skill_id": skill.id,
                "name": skill.name,
                "scope_type": skill.scope_type,
                "scope_id": skill.scope_id,
                "revision_id": revision.id,
                "revision_number": revision.revision_number,
                "instructions": revision.instructions,
                "tokens": tokens,
            }
        )
        used += tokens
    return selected


async def activate_learning_suggestion(
    suggestion_id: str, expected_version: int
) -> dict[str, Any]:
    """Atomically create an immutable revision and move the active pointer."""
    async with db.async_session() as session:
        resource = await activate_learning_suggestion_in_session(
            session,
            suggestion_id,
            expected_version,
        )
        await session.commit()
        return resource


async def activate_learning_suggestion_in_session(
    session,
    suggestion_id: str,
    expected_version: int,
) -> dict[str, Any]:
    """Apply a suggestion without committing so APIs can include audit/replay."""
    from src.core.rag_engine import get_embedding

    suggestion = await session.get(LearningSuggestionModel, suggestion_id)
    if not suggestion:
        raise KeyError("LEARNING_SUGGESTION_NOT_FOUND")
    if suggestion.version != expected_version:
        raise RuntimeError("VERSION_CONFLICT")
    if suggestion.status == "approved" and suggestion.skill_id:
        skill = await session.get(SkillModel, suggestion.skill_id)
        return {
            "suggestion_id": suggestion.id,
            "skill_id": suggestion.skill_id,
            "revision_id": skill.active_revision_id if skill else "",
            "recovered": True,
        }
    if suggestion.status != "pending":
        raise ValueError("Only pending suggestions can be approved.")
    skill = (
        await session.get(SkillModel, suggestion.skill_id)
        if suggestion.skill_id
        else None
    )
    if skill is None:
        skill = SkillModel(
            name=suggestion.title,
            description=suggestion.rationale,
            scope_type=suggestion.scope_type,
            scope_id=suggestion.scope_id,
            tags=list((suggestion.evidence or {}).get("tags") or []),
        )
        session.add(skill)
        await session.flush()
    revision_number = (
        int(
            await session.scalar(
                select(func.max(SkillRevisionModel.revision_number)).where(
                    SkillRevisionModel.skill_id == skill.id
                )
            )
            or 0
        )
        + 1
    )
    instructions = suggestion.proposed_instructions
    revision = SkillRevisionModel(
        skill_id=skill.id,
        revision_number=revision_number,
        instructions=instructions,
        token_count=_tokens(instructions),
        vector=await get_embedding(instructions),
        evidence=suggestion.evidence or {},
        created_by="administrator",
    )
    session.add(revision)
    await session.flush()
    skill.active_revision_id, skill.version = revision.id, skill.version + 1
    suggestion.skill_id, suggestion.status = skill.id, "approved"
    suggestion.version += 1
    return {
        "suggestion_id": suggestion.id,
        "skill_id": skill.id,
        "revision_id": revision.id,
        "revision_number": revision_number,
    }


async def graph_snapshot(status: str | None = None) -> dict[str, Any]:
    async with db.async_session() as session:
        entity_query = select(BrainEntityModel)
        relationship_query = select(BrainRelationshipModel)
        if status:
            entity_query = entity_query.where(BrainEntityModel.status == status)
            relationship_query = relationship_query.where(
                BrainRelationshipModel.status == status
            )
        entities = (
            (
                await session.execute(
                    entity_query.order_by(BrainEntityModel.name).limit(500)
                )
            )
            .scalars()
            .all()
        )
        relationships = (
            (await session.execute(relationship_query.limit(1000))).scalars().all()
        )
        fact_query = select(BrainFactModel)
        if status:
            fact_query = fact_query.where(BrainFactModel.status == status)
        facts = (await session.execute(fact_query.limit(1000))).scalars().all()
        recent_retrievals = (
            (
                await session.execute(
                    select(RetrievalCacheModel).where(
                        RetrievalCacheModel.created_at
                        >= utcnow() - timedelta(minutes=20)
                    )
                )
            )
            .scalars()
            .all()
        )
    active_document_ids = {
        str(result.get("document_id"))
        for cache in recent_retrievals
        for result in (cache.result or {}).get("results", [])
        if result.get("document_id")
    }
    active_fact_ids = {
        fact.id for fact in facts if fact.source_document_id in active_document_ids
    }
    active_entity_ids = {
        str(fact.subject_entity_id)
        for fact in facts
        if fact.id in active_fact_ids and fact.subject_entity_id
    }
    entity_nodes = [
        {
            "id": entity.id,
            "label": entity.name,
            "type": entity.entity_type,
            "status": entity.status,
            "confidence": entity.confidence,
            "version": entity.version,
            "active": entity.id in active_entity_ids,
        }
        for entity in entities
    ]
    fact_nodes = [
        {
            "id": fact.id,
            "label": f"{fact.predicate}: {fact.value_text[:80]}",
            "type": "fact",
            "status": fact.status,
            "confidence": fact.confidence,
            "version": fact.version,
            "active": fact.id in active_fact_ids,
        }
        for fact in facts
    ]
    relationship_edges = [
        {
            "id": relationship.id,
            "source": relationship.source_entity_id,
            "target": relationship.target_entity_id,
            "label": relationship.relationship_type,
            "status": relationship.status,
            "version": relationship.version,
            "active": bool(
                relationship.source_fact_id
                and relationship.source_fact_id in active_fact_ids
            ),
        }
        for relationship in relationships
    ]
    fact_edges = [
        {
            "id": f"fact-subject:{fact.id}",
            "source": str(fact.subject_entity_id),
            "target": fact.id,
            "label": "asserts",
            "status": fact.status,
            "version": fact.version,
            "active": fact.id in active_fact_ids,
        }
        for fact in facts
        if fact.subject_entity_id
    ]
    return {
        "nodes": [*entity_nodes, *fact_nodes],
        "edges": [*relationship_edges, *fact_edges],
        "facts": [
            {
                "id": fact.id,
                "subject_id": fact.subject_entity_id,
                "predicate": fact.predicate,
                "value": fact.value_text,
                "status": fact.status,
                "confidence": fact.confidence,
                "citation": fact.citation_text,
                "version": fact.version,
            }
            for fact in facts
        ],
    }
