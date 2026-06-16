"""``TemporalStore`` — the append-only evolution log (feat-009).

A stdlib-``sqlite3`` sidecar at ``.ckg/temporal.db``, deliberately *separate*
from the graph/vector stores: it keeps the current-graph hot path and both
store adapters untouched (design-009 §4.2), is trivially prunable, and is absent
for non-git / temporal-off repos. Writes are append-only and idempotent per
``(symbol_id, commit, event, ref)`` so a crashed-then-retried refresh stays
consistent.

Chunk 1 implements the ``events`` table (node lifecycle); the ``aggregates``
table (churn/authorship, chunk 2) is created here but populated later.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from .events import Entity, Event, EventKind

_DB = "temporal.db"

_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS events (
        symbol_id  TEXT NOT NULL,
        entity     TEXT NOT NULL,
        event      TEXT NOT NULL,
        commit_sha TEXT NOT NULL,
        ts         INTEGER NOT NULL,
        ref        TEXT
    )""",
    # idempotency: the same lifecycle fact recorded twice is a no-op. COALESCE so
    # a NULL ref participates in uniqueness (SQLite treats NULLs as distinct).
    """CREATE UNIQUE INDEX IF NOT EXISTS events_unique
        ON events(symbol_id, commit_sha, event, COALESCE(ref, ''))""",
    "CREATE INDEX IF NOT EXISTS events_by_symbol ON events(symbol_id)",
    "CREATE INDEX IF NOT EXISTS events_by_ts ON events(ts)",
    # aggregates: periodic, bounded — populated in chunk 2 (churn/authorship).
    """CREATE TABLE IF NOT EXISTS aggregates (
        symbol_id        TEXT PRIMARY KEY,
        churn_30d        INTEGER,
        churn_90d        INTEGER,
        top_authors      TEXT,
        introduced_sha   TEXT,
        introduced_ts    INTEGER,
        last_changed_sha TEXT,
        last_changed_ts  INTEGER
    )""",
]


class TemporalStore:
    """Embedded SQLite evolution log. Opened once per index/refresh; each
    operation uses its own short-lived connection (SQLite connections are not
    shareable across threads, and ops run via ``asyncio.to_thread``)."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def open(cls, root: str | Path) -> TemporalStore:
        """Create (if needed) the sidecar under ``root`` (the ``.ckg`` dir) and
        ensure the schema exists."""
        p = Path(root) / _DB
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        try:
            for ddl in _SCHEMA:
                conn.execute(ddl)
            conn.commit()
        finally:
            conn.close()
        return cls(p)

    async def record(self, events: list[Event]) -> int:
        """Append events; return the number newly inserted (duplicates ignored)."""
        if not events:
            return 0
        return await asyncio.to_thread(self._record_sync, events)

    def _record_sync(self, events: list[Event]) -> int:
        conn = sqlite3.connect(str(self._path))
        try:
            cur = conn.executemany(
                "INSERT OR IGNORE INTO events"
                "(symbol_id, entity, event, commit_sha, ts, ref) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (e.symbol_id, e.entity.value, e.event.value, e.commit, e.ts, e.ref)
                    for e in events
                ],
            )
            conn.commit()
            return cur.rowcount if cur.rowcount is not None else 0
        finally:
            conn.close()

    async def events_for(self, symbol_id: str) -> list[Event]:
        """All events for one symbol, oldest first."""
        return await asyncio.to_thread(self._events_for_sync, symbol_id)

    def _events_for_sync(self, symbol_id: str) -> list[Event]:
        conn = sqlite3.connect(str(self._path))
        try:
            rows = conn.execute(
                "SELECT symbol_id, entity, event, commit_sha, ts, ref FROM events "
                "WHERE symbol_id = ? ORDER BY ts, rowid",
                (symbol_id,),
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_event(r) for r in rows]

    async def all_events(self) -> list[Event]:
        """Every event, oldest first (test/inspection helper)."""
        return await asyncio.to_thread(self._all_events_sync)

    def _all_events_sync(self) -> list[Event]:
        conn = sqlite3.connect(str(self._path))
        try:
            rows = conn.execute(
                "SELECT symbol_id, entity, event, commit_sha, ts, ref FROM events "
                "ORDER BY ts, rowid"
            ).fetchall()
        finally:
            conn.close()
        return [_row_to_event(r) for r in rows]

    async def prune(self, before_ts: int) -> int:
        """Delete CLOSED events older than ``before_ts`` (retention horizon).
        OPENED events are kept (they anchor 'introduced'); full retention math
        lands in chunk 5. Returns rows removed."""
        return await asyncio.to_thread(self._prune_sync, before_ts)

    def _prune_sync(self, before_ts: int) -> int:
        conn = sqlite3.connect(str(self._path))
        try:
            cur = conn.execute(
                "DELETE FROM events WHERE event = ? AND ts < ?",
                (EventKind.CLOSED.value, before_ts),
            )
            conn.commit()
            return cur.rowcount if cur.rowcount is not None else 0
        finally:
            conn.close()


def _row_to_event(r: tuple[Any, ...]) -> Event:
    return Event(
        symbol_id=r[0],
        entity=Entity(r[1]),
        event=EventKind(r[2]),
        commit=r[3],
        ts=r[4],
        ref=r[5],
    )
