"""Stable production council registry.

API and worker code should import from this module instead of individual
council packages.  The registry is also the scope boundary: Strategy and
Support are intentionally not constructible in the production build.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from src.core.council_base import BaseCouncil, CouncilRunResult

ALLOWED_COUNCILS = frozenset({"grant", "sales", "content"})


def create_council(name: str, *, checkpointer: Any = None) -> BaseCouncil:
    key = name.strip().lower()
    if key == "grant":
        from src.councils.grant.council import GrantCouncil

        return GrantCouncil(checkpointer=checkpointer)
    if key == "sales":
        from src.councils.sales.council import SalesCouncil

        return SalesCouncil(checkpointer=checkpointer)
    if key == "content":
        from src.councils.content.council import ContentCouncil

        return ContentCouncil(checkpointer=checkpointer)
    raise ValueError(
        f"Unsupported council {name!r}; allowed councils are grant, sales, and content."
    )


async def run_council(
    name: str,
    task_description: str,
    *,
    context: dict[str, Any] | None = None,
    priority: str = "medium",
    task_id: str | None = None,
    progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> CouncilRunResult:
    """One-call execution interface for the API and durable worker."""
    return await create_council(name).run(
        task_description,
        context=context,
        priority=priority,
        task_id=task_id,
        progress_callback=progress_callback,
    )


__all__ = [
    "ALLOWED_COUNCILS",
    "CouncilRunResult",
    "create_council",
    "run_council",
]
