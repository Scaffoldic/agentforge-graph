"""Framework-aware extractors (feat-011): export framework semantics —
routes, ORM models, DI — as graph edges agents can traverse.

A ``FrameworkPack`` rides feat-002's per-file extraction and emits framework
nodes/edges into the file's ``FileSubgraph`` (so feat-004 incrementality
applies for free). v0.4 MVP ships the **FastAPI** routes pack; ORM/DI and more
frameworks follow over the same harness. Zero ``agentforge`` imports (ADR-0001).
"""

from __future__ import annotations

from .base import FrameworkFacts, FrameworkPack
from .detect import active_frameworks
from .extractor import FrameworkExtractor
from .registry import (
    BUILTIN_FRAMEWORK_PACKS,
    FrameworkRegistry,
    builtin_framework_registry,
)

__all__ = [
    "FrameworkFacts",
    "FrameworkPack",
    "FrameworkExtractor",
    "FrameworkRegistry",
    "BUILTIN_FRAMEWORK_PACKS",
    "builtin_framework_registry",
    "active_frameworks",
]
