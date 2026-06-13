"""Generic model-provider registry: a config provider-name → builder callable.

Mirrors the storage driver registry (``store/registry.py``) for the model layer
(embedders, judges, summarizers). Built-in providers are registered in each
role's ``_BUILTINS`` map; third-party providers register out-of-tree via
entry-point groups, so they install as ``pip install`` + one config line with no
core change.

Engine-shared, deterministic — must not import ``agentforge`` (ADR-0001). Only
stdlib ``importlib.metadata`` is used here.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import cast


class ProviderNotFound(ValueError):
    """Raised when a config provider name matches no built-in and no entry point."""


def resolve_provider[T](name: str, builtins: dict[str, T], group: str, *, role: str) -> T:
    """Return the builder registered for ``name`` — a built-in first, otherwise an
    entry point in ``group``. Raises ``ProviderNotFound`` (listing the built-ins
    and the entry-point group) when nothing matches."""
    if name in builtins:
        return builtins[name]
    for ep in entry_points(group=group):
        if ep.name == name:
            return cast(T, ep.load())
    known = sorted(builtins)
    raise ProviderNotFound(
        f"unknown {role} provider {name!r}; built-in providers: {known} "
        f"(third-party providers register under the {group!r} entry-point group)"
    )
