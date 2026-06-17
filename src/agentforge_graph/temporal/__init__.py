"""feat-009 temporal / git-evolution layer.

An append-only evolution log (``.ckg/temporal.db``) populated by the feat-004
refresh, recording when each symbol was introduced/removed at which commit —
the basis for ``history`` / ``changed_since`` / ``as_of`` and for churn/age
ranking signals. Higher layer: imports ``core``/``store``/``ingest``; the
deterministic engine core never imports this. Default off (opt-in). See
``docs/design/design-009-temporal-evolution-layer.md``.
"""

from .backfill import BackfillReport, parse_history, run_backfill
from .events import Author, Change, Entity, Event, EventKind, SymbolHistory
from .index import TemporalError, TemporalIndex
from .mining import ChurnMiner, SymbolAggregate
from .recorder import SqliteTemporalRecorder, build_recorder, seed_symbols
from .store import TemporalStore

__all__ = [
    "Author",
    "BackfillReport",
    "Change",
    "ChurnMiner",
    "Entity",
    "Event",
    "EventKind",
    "SqliteTemporalRecorder",
    "SymbolAggregate",
    "SymbolHistory",
    "TemporalError",
    "TemporalIndex",
    "TemporalStore",
    "build_recorder",
    "parse_history",
    "run_backfill",
    "seed_symbols",
]
