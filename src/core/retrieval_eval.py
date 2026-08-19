"""Deterministic evaluation harness for the native Council Brain retriever."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from statistics import median
from typing import Any, Awaitable, Callable

from src.core import database as db
from src.core.models import RetrievalEvaluationModel
from src.core.rag_engine import PIPELINE_VERSION, search_knowledge


SearchFunction = Callable[..., Awaitable[dict[str, Any]]]


def load_evaluation_dataset(path: str | Path) -> dict[str, Any]:
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(dataset.get("cases"), list) or not dataset["cases"]:
        raise ValueError("Retrieval evaluation dataset must contain at least one case.")
    return dataset


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1))
    return ordered[index]


async def run_retrieval_evaluation(
    dataset: dict[str, Any], *, search_fn: SearchFunction = search_knowledge,
    persist: bool = True,
) -> dict[str, Any]:
    """Measure precision, citation validity, latency, and baseline deltas."""
    cases = dataset.get("cases") or []
    if not cases:
        raise ValueError("Retrieval evaluation dataset must contain at least one case.")
    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []
    precision_values: list[float] = []
    citation_values: list[float] = []
    for case in cases:
        expected = set(case.get("expected_document_hashes") or [])
        top_k = max(1, min(int(case.get("top_k") or 5), 20))
        started = time.perf_counter()
        response = await search_fn(
            str(case.get("query") or ""), top_k=top_k,
            document_hashes=case.get("document_hashes") or None,
            collection_ids=case.get("collection_ids") or None,
            graph_expansion=bool(case.get("graph_expansion", True)),
        )
        latency_ms = (time.perf_counter() - started) * 1000.0
        results = response.get("results") or []
        relevant = sum(1 for item in results if item.get("doc_hash") in expected)
        precision = relevant / len(results) if results else 0.0
        citation_valid = sum(
            1 for item in results
            if isinstance(item.get("source_start"), int)
            and isinstance(item.get("source_end"), int)
            and item["source_start"] >= 0
            and item["source_end"] > item["source_start"]
            and bool(item.get("citation"))
        )
        citation_correctness = citation_valid / len(results) if results else 0.0
        latencies.append(latency_ms)
        precision_values.append(precision)
        citation_values.append(citation_correctness)
        per_case.append({
            "id": case.get("id"), "query": case.get("query"),
            "precision_at_k": precision, "citation_correctness": citation_correctness,
            "latency_ms": latency_ms, "result_count": len(results),
            "warnings": response.get("warnings") or [],
        })

    baseline = dataset.get("baseline_metrics") or {}
    precision = sum(precision_values) / len(precision_values)
    citation_correctness = sum(citation_values) / len(citation_values)
    metrics = {
        "case_count": len(cases), "precision_at_k": precision,
        "citation_correctness": citation_correctness,
        "latency_p50_ms": median(latencies),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "provider_cost_usd": 0.0,
        "baseline": baseline,
        "delta": {
            "precision_at_k": precision - float(baseline.get("precision_at_k", 0.0)),
            "citation_correctness": citation_correctness - float(baseline.get("citation_correctness", 0.0)),
            "latency_p50_ms": median(latencies) - float(baseline.get("latency_p50_ms", 0.0)),
            "provider_cost_usd": 0.0 - float(baseline.get("provider_cost_usd", 0.0)),
        },
        "cases": per_case,
    }
    evaluation = RetrievalEvaluationModel(
        dataset_version=str(dataset.get("version") or "unversioned"),
        pipeline_version=PIPELINE_VERSION, metrics=metrics, status="completed",
    )
    if persist:
        async with db.async_session() as session:
            session.add(evaluation)
            await session.commit()
            await session.refresh(evaluation)
    return {
        "id": evaluation.id if persist else None,
        "dataset_version": evaluation.dataset_version,
        "pipeline_version": evaluation.pipeline_version,
        "metrics": metrics, "status": evaluation.status,
    }
