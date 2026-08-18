"""Compatibility shim for the retired in-process APScheduler runtime.

Production schedules are evaluated by :mod:`src.worker` and persisted as
``workflow_runs``. Keeping this module side-effect free prevents API imports
from starting duplicate or out-of-scope jobs.
"""

from __future__ import annotations


def set_tasks_store(_: dict) -> None:
    """Legacy no-op; in-memory workflow state is no longer supported."""


def start_scheduler() -> None:
    raise RuntimeError(
        "The in-process scheduler was removed. Run `python -m src.worker` instead."
    )
