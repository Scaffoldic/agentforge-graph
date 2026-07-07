"""feat-014: the pure trigger-policy core.

Given a stream of :class:`Event` and an injected clock, ``TriggerPolicy``
decides *when* a batch of changes becomes a refresh. It holds no filesystem, no
timers, and never sleeps — the whole policy matrix is unit-tested by feeding
``observe`` / ``due`` / ``next_due_in`` a scripted ``now`` (seconds, float). The
fs-watch loop (:mod:`.runner`) is a thin adapter that turns real time and real
file events into calls on this object.

Zero ``agentforge`` imports (ADR-0001).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

TRIGGERS = ("on-commit", "on-idle", "on-save", "interval", "manual")

# Slack on the "window elapsed" comparison. When the loop waits exactly
# ``next_due_in`` seconds and the clock lands a float-ulp short of the threshold,
# treat it as elapsed anyway — a sub-microsecond boundary is never meaningful for
# a debounce/idle window, and without it a timeout can spuriously not fire.
_EPS = 1e-6


class EventKind(Enum):
    FILE = "file"  # a source file changed (already ignore-filtered)
    GIT = "git"  # .git/HEAD or refs changed (commit / branch switch)


@dataclass(frozen=True)
class Event:
    kind: EventKind
    path: str = ""


@dataclass(frozen=True)
class WatchSettings:
    """Resolved trigger settings (from ``WatchConfig`` + CLI overrides)."""

    trigger: str = "on-commit"
    debounce_ms: int = 1000
    idle_ms: int = 3000
    interval_ms: int = 60000

    def __post_init__(self) -> None:
        if self.trigger not in TRIGGERS:
            raise ValueError(f"unknown trigger {self.trigger!r}; expected one of {TRIGGERS}")


class TriggerPolicy:
    """Trigger state machine. All times are seconds (float); the caller owns the
    clock so tests are deterministic."""

    def __init__(self, settings: WatchSettings, *, now: float = 0.0) -> None:
        self.settings = settings
        self._pending = False
        self._last_event = 0.0  # last counted FILE/GIT event (debounce/idle)
        self._last_git = 0.0  # last GIT event (on-commit)
        self._last_fire = now  # last refresh (interval)

    # --- inputs -----------------------------------------------------------

    def observe(self, event: Event, now: float) -> None:
        """Record an event if it counts for the active trigger."""
        t = self.settings.trigger
        if t == "manual":
            return
        if t == "on-commit":
            if event.kind is EventKind.GIT:
                self._pending = True
                self._last_git = now
            return
        # on-idle / on-save / interval: any (already-filtered) event counts. A
        # commit is a real change too, so GIT counts here as well.
        self._pending = True
        self._last_event = now

    # --- decisions --------------------------------------------------------

    def due(self, now: float) -> bool:
        """Whether a refresh should fire at ``now`` given pending state."""
        if not self._pending:
            return False
        t = self.settings.trigger
        if t == "manual":
            return False
        if t == "on-commit":
            return now - self._last_git >= self._sec("debounce_ms") - _EPS
        if t == "on-idle":
            return now - self._last_event >= self._sec("idle_ms") - _EPS
        if t == "on-save":
            return now - self._last_event >= self._sec("debounce_ms") - _EPS
        if t == "interval":
            return now - self._last_fire >= self._sec("interval_ms") - _EPS
        return False

    def next_due_in(self, now: float) -> float | None:
        """Seconds until :meth:`due` flips True given the current pending state,
        clamped at 0; ``None`` when nothing is pending (wait indefinitely). Drives
        the loop timeout so an idle/interval window elapses without a new event."""
        if not self._pending or self.settings.trigger == "manual":
            return None
        t = self.settings.trigger
        if t == "on-commit":
            target = self._last_git + self._sec("debounce_ms")
        elif t == "on-idle":
            target = self._last_event + self._sec("idle_ms")
        elif t == "on-save":
            target = self._last_event + self._sec("debounce_ms")
        elif t == "interval":
            target = self._last_fire + self._sec("interval_ms")
        else:  # pragma: no cover - exhaustive
            return None
        return max(0.0, target - now)

    def reset(self, now: float) -> None:
        """Clear pending state after a refresh fired."""
        self._pending = False
        self._last_fire = now

    @property
    def pending(self) -> bool:
        return self._pending

    def _sec(self, field: str) -> float:
        return float(getattr(self.settings, field)) / 1000.0
