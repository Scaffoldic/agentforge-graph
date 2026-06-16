"""``SqliteTemporalRecorder`` — the write port the indexer drives (feat-009).

The ``IncrementalIndexer`` calls ``open``/``close`` as it applies a diff (it is
the only writer that sees both the old and new state of a file); the recorder
buffers those into ``Event``s and writes them in a single transaction on
``flush()`` at end-of-refresh — mirroring how ``IndexMeta`` is saved last, so a
crash leaves a consistent log. ``open``/``close`` are sync (buffering); only
``flush`` touches SQLite.

Structurally satisfies ``ingest.incremental.ports.TemporalRecorder`` so the
deterministic ``ingest`` layer depends on a Protocol, not on ``temporal``.
"""

from __future__ import annotations

from collections.abc import Iterable

from agentforge_graph.core import GraphQuery, GraphStore, NodeKind

from .events import Entity, Event, EventKind
from .store import TemporalStore

_ALL = 10_000_000
_SYMBOL_KINDS = (NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD)


class SqliteTemporalRecorder:
    def __init__(self, store: TemporalStore) -> None:
        self._store = store
        self._buf: list[Event] = []

    def open(self, symbol_ids: Iterable[str], at: str, ts: int) -> None:
        self._buf.extend(
            Event(symbol_id=sid, event=EventKind.OPENED, commit=at, ts=ts, entity=Entity.NODE)
            for sid in symbol_ids
        )

    def close(self, symbol_ids: Iterable[str], at: str, ts: int) -> None:
        self._buf.extend(
            Event(symbol_id=sid, event=EventKind.CLOSED, commit=at, ts=ts, entity=Entity.NODE)
            for sid in symbol_ids
        )

    async def flush(self) -> None:
        if not self._buf:
            return
        events, self._buf = self._buf, []
        await self._store.record(events)


def build_recorder(root: str) -> SqliteTemporalRecorder:
    """Open the sidecar under ``root`` (the ``.ckg`` dir) and wrap it."""
    return SqliteTemporalRecorder(TemporalStore.open(root))


async def seed_symbols(
    graph: GraphStore, recorder: SqliteTemporalRecorder, commit: str, ts: int
) -> None:
    """Open intervals for every code symbol currently in the graph — used after
    a full index so 'introduced' is anchored at the index commit. Idempotent: a
    re-index of the same commit re-opens the same events (deduped by the store)."""
    nodes = (await graph.query(GraphQuery(kinds=list(_SYMBOL_KINDS), limit=_ALL))).nodes
    recorder.open([n.id for n in nodes], commit, ts)
    await recorder.flush()
