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
