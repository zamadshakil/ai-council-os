"""Request/job-scoped access to decrypted integration configuration."""

from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Mapping


_ACTIVE_CONFIGURATION: ContextVar[Mapping[str, str]] = ContextVar(
    "integration_configuration", default={}
)


def integration_value(name: str, default: str = "") -> str:
    """Return a scoped portal credential first, then the server environment."""
    value = _ACTIVE_CONFIGURATION.get().get(name)
    if value is not None:
        return str(value)
    return os.getenv(name, default)


@contextmanager
def use_integration_configuration(values: Mapping[str, str]) -> Iterator[None]:
    """Expose decrypted values only inside the current async/thread context."""
    token = _ACTIVE_CONFIGURATION.set(dict(values))
    try:
        yield
    finally:
        _ACTIVE_CONFIGURATION.reset(token)
