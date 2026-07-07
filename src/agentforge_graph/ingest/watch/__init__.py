"""feat-014: local watch mode — re-run the feat-004 incremental ``refresh()`` on
a configurable trigger.

The pure trigger core (:mod:`.policy`) is clock-injected and fully unit-tested;
the fs-watch loop (:mod:`.runner` + :mod:`.source`) is a thin adapter over it.
``ckg watch`` refuses a central / read-only store (:mod:`.guard`) — that
topology's freshness is CI's job (``ckg ci init``). Framework-free (ADR-0001).
"""

from __future__ import annotations

from .filter import WatchFilter
from .gitwatch import branch_active, current_branch, head_ref
from .guard import WatchGuardError, ensure_watchable
from .policy import Event, EventKind, TriggerPolicy, WatchSettings
from .runner import (
    WatchRunner,
    WatchStatus,
    WatchStopped,
    run_once,
    run_watch,
    status,
)

__all__ = [
    "Event",
    "EventKind",
    "TriggerPolicy",
    "WatchSettings",
    "WatchFilter",
    "WatchGuardError",
    "ensure_watchable",
    "branch_active",
    "current_branch",
    "head_ref",
    "WatchRunner",
    "WatchStatus",
    "WatchStopped",
    "run_watch",
    "run_once",
    "status",
]
