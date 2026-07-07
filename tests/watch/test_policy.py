"""feat-014: the trigger-policy matrix, with an injected clock (no I/O, no sleep)."""

from __future__ import annotations

from agentforge_graph.ingest.watch import Event, EventKind, TriggerPolicy, WatchSettings

FILE = Event(EventKind.FILE, "a.py")
GIT = Event(EventKind.GIT, ".git/HEAD")


def _p(trigger: str, **kw: int) -> TriggerPolicy:
    return TriggerPolicy(WatchSettings(trigger=trigger, **kw), now=0.0)


def test_manual_never_fires() -> None:
    p = _p("manual")
    p.observe(FILE, 1.0)
    p.observe(GIT, 2.0)
    assert p.due(1_000.0) is False
    assert p.next_due_in(1_000.0) is None


def test_on_save_debounces_bursts() -> None:
    p = _p("on-save", debounce_ms=1000)
    p.observe(FILE, 10.0)  # last_event = 10.0, window 1s
    assert p.due(10.5) is False  # still within debounce
    p.observe(FILE, 10.4)  # a burst save resets the window
    assert p.due(11.0) is False  # 11.0 - 10.4 = 0.6 < 1.0
    assert p.due(11.4) is True  # quiet for 1s → fire
    assert p.next_due_in(10.4) == 1.0


def test_on_idle_uses_idle_window() -> None:
    p = _p("on-idle", idle_ms=3000)
    p.observe(FILE, 5.0)
    assert p.due(7.0) is False  # 2s < 3s
    assert p.due(8.0) is True
    assert p.next_due_in(6.0) == 2.0


def test_on_commit_ignores_saves_fires_on_git() -> None:
    p = _p("on-commit", debounce_ms=1000)
    p.observe(FILE, 1.0)  # a plain save must NOT arm the trigger
    assert p.pending is False
    assert p.next_due_in(100.0) is None
    p.observe(GIT, 10.0)  # a commit / branch switch arms it
    assert p.pending is True
    assert p.due(10.5) is False  # small debounce coalesces a switch storm
    assert p.due(11.0) is True


def test_interval_fires_only_when_dirty() -> None:
    p = _p("interval", interval_ms=60000)  # last_fire = 0.0
    assert p.due(100.0) is False  # nothing pending, never fires
    p.observe(FILE, 5.0)
    assert p.due(30.0) is False  # 30 - 0 < 60
    assert p.due(61.0) is True  # 61 - last_fire(0) >= 60
    p.reset(61.0)
    assert p.due(100.0) is False  # cleared until dirtied again


def test_reset_clears_pending_and_sets_last_fire() -> None:
    p = _p("interval", interval_ms=1000)
    p.observe(FILE, 1.0)
    p.reset(5.0)
    assert p.pending is False
    p.observe(FILE, 5.5)
    assert p.due(5.9) is False  # 5.9 - 5.0 < 1.0
    assert p.due(6.0) is True


def test_bad_trigger_rejected() -> None:
    import pytest

    with pytest.raises(ValueError):
        WatchSettings(trigger="nope")
