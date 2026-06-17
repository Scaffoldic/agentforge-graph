"""Value types for the temporal evolution log (feat-009).

An ``Event`` is one lifecycle record for a symbol (or, later, an edge): it was
``opened`` (first observed / re-introduced) or ``closed`` (removed) at a commit,
or ``succeeds`` another symbol (rename lineage). These are *commit-validity*
facts — when something was true in the repo — not ingestion-time facts (the
design's bi-temporal-lite scope; see design-009 §3).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EventKind(StrEnum):
    OPENED = "opened"  # symbol first observed / re-introduced at `commit`
    CLOSED = "closed"  # symbol removed at `commit`
    SUCCEEDS = "succeeds"  # `symbol_id` is the successor of `ref` (rename lineage)


class Entity(StrEnum):
    NODE = "node"
    EDGE = "edge"


class Event(BaseModel):
    """One append-only lifecycle record in the evolution log."""

    model_config = ConfigDict(frozen=True)

    symbol_id: str
    event: EventKind
    commit: str
    ts: int = 0  # commit author time (epoch seconds); 0 if unknown / non-git
    entity: Entity = Entity.NODE
    ref: str | None = None  # SUCCEEDS: the prior symbol id this one supersedes


# --- read-side value types (chunk 3 read APIs) ----------------------------


class Author(BaseModel):
    """An author and how many commits they made to a symbol's span (within the
    mined window)."""

    model_config = ConfigDict(frozen=True)

    name: str
    commits: int


class Change(BaseModel):
    """One symbol that changed since a reference commit — the unit returned by
    ``changed_since``."""

    model_config = ConfigDict(frozen=True)

    symbol_id: str
    path: str
    kind: str  # "opened" | "closed" | "modified"
    commit: str
    ts: int


class SymbolHistory(BaseModel):
    """A symbol's evolution at a glance: when it was introduced / last changed,
    its churn windows, its authors, and the raw lifecycle events. Read from the
    sidecar (+ the current graph for the live span)."""

    model_config = ConfigDict(frozen=True)

    symbol_id: str
    introduced: str = ""  # commit sha (prefer the OPENED event; else mined)
    introduced_ts: int = 0
    last_changed: str = ""
    last_changed_ts: int = 0
    churn_30d: int = 0
    churn_90d: int = 0
    authors: list[Author] = []
    events: list[Event] = []
