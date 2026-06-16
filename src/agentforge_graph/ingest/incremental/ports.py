"""Ports the incremental indexer depends on but does not own (feat-009).

The ``IncrementalIndexer`` records symbol lifecycle (opened/closed) as it
applies a diff, but the deterministic ``ingest`` layer must not import the
higher ``temporal`` layer (ADR-0001 spirit). So it depends on this structural
``Protocol``; the concrete ``temporal.SqliteTemporalRecorder`` satisfies it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable


@runtime_checkable
class TemporalRecorder(Protocol):
    """Write port for the evolution log. ``open``/``close`` buffer; ``flush``
    persists in one transaction at end-of-refresh."""

    def open(self, symbol_ids: Iterable[str], at: str, ts: int) -> None: ...

    def close(self, symbol_ids: Iterable[str], at: str, ts: int) -> None: ...

    async def flush(self) -> None: ...
