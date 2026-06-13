"""Incremental indexing (feat-004): re-index only the diff.

A thin coordination layer over the feat-002/003 primitives —
``ChangeDetector`` diffs the working tree against the ``IndexMeta`` manifest,
``IncrementalIndexer`` applies the resulting ``ChangeSet`` (delete → re-extract
→ scoped re-resolve), and ``DirtySet`` records what each enricher must redo.
Zero ``agentforge`` imports (ADR-0001).
"""

from __future__ import annotations

from .detect import ChangeDetector, ChangeSet, DetectResult
from .dirty import DirtySet
from .indexer import IncrementalIndexer
from .meta import IndexMeta, pack_fingerprint

__all__ = [
    "ChangeDetector",
    "ChangeSet",
    "DetectResult",
    "DirtySet",
    "IncrementalIndexer",
    "IndexMeta",
    "pack_fingerprint",
]
