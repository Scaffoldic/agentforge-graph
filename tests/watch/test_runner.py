"""feat-014: the watch loop, driven by a scripted event stream + a fake clock.

No filesystem, no watchfiles, no sleeping — a scripted ``pull`` advances a fake
clock so debounce/idle windows elapse deterministically, and a fake ``refresh``
records how many times (and when) the loop fired.
"""

from __future__ import annotations

from agentforge_graph.ingest.watch import Event, EventKind, WatchSettings
from agentforge_graph.ingest.watch.runner import WatchRunner, WatchStopped


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class ScriptedPull:
    """Steps: ("file", t[, path]) | ("git", t) | ("switch", t, branch) | ("wait",).
    A ``wait`` honors the loop's requested timeout (the window elapses); an
    exhausted script raises WatchStopped to end the loop."""

    def __init__(self, clock: Clock, steps: list[tuple], branch: list[str]) -> None:
        self.clock = clock
        self.steps = steps
        self.branch = branch  # 1-element mutable holder
        self.i = 0

    async def __call__(self, timeout: float | None) -> Event | None:
        if self.i >= len(self.steps):
            raise WatchStopped
        step = self.steps[self.i]
        self.i += 1
        kind = step[0]
        if kind == "file":
            self.clock.t = step[1]
            return Event(EventKind.FILE, step[2] if len(step) > 2 else "a.py")
        if kind == "git":
            self.clock.t = step[1]
            return Event(EventKind.GIT, ".git/HEAD")
        if kind == "switch":
            self.clock.t = step[1]
            self.branch[0] = step[2]
            return Event(EventKind.GIT, ".git/HEAD")
        if kind == "wait":
            assert timeout is not None, "wait step but nothing is pending (timeout=None)"
            self.clock.t += timeout
            return None
        raise AssertionError(kind)


def _make(settings, steps, *, branch="", include=None, exclude=None):  # type: ignore[no-untyped-def]
    clock = Clock()
    holder = [branch]
    fired: list[float] = []
    gates: list[tuple[bool, str]] = []

    async def refresh() -> object:
        fired.append(clock.t)
        return object()

    runner = WatchRunner(
        settings,
        pull=ScriptedPull(clock, steps, holder),
        refresh=refresh,
        branch_of=lambda: holder[0],
        include=include if include is not None else ["*"],
        exclude=exclude if exclude is not None else [],
        now=clock,
        on_refresh=lambda r: None,
        on_gate=lambda a, b: gates.append((a, b)),
    )
    return runner, fired, gates


async def test_burst_coalesces_to_one_refresh() -> None:
    # two saves inside one idle window → a single refresh (single-flight/debounce)
    settings = WatchSettings(trigger="on-idle", idle_ms=100)
    steps = [("file", 1.0), ("file", 1.05), ("wait",), ("file", 5.0), ("wait",)]
    runner, fired, _ = _make(settings, steps)
    n = await runner.run()
    assert n == 2
    assert len(fired) == 2


async def test_on_commit_ignores_saves_fires_on_git() -> None:
    settings = WatchSettings(trigger="on-commit", debounce_ms=100)
    steps = [("file", 1.0), ("file", 2.0), ("git", 3.0), ("wait",)]
    runner, fired, _ = _make(settings, steps)
    n = await runner.run()
    assert n == 1  # the two saves did nothing; the commit fired once


async def test_branch_gate_activates_on_switch() -> None:
    # start on an excluded branch (idle), switch to a watched branch, then edit
    settings = WatchSettings(trigger="on-idle", idle_ms=100)
    steps = [
        ("file", 1.0),  # ignored — gated out on main
        ("switch", 2.0, "feature/x"),  # git event flips the gate active
        ("file", 3.0),
        ("wait",),
    ]
    runner, fired, gates = _make(settings, steps, branch="main", include=["*"], exclude=["main"])
    n = await runner.run()
    assert n == 1
    assert gates[0] == (False, "main")  # started gated out
    assert (True, "feature/x") in gates  # activated on switch


async def test_manual_never_refreshes() -> None:
    settings = WatchSettings(trigger="manual")
    steps = [("file", 1.0), ("git", 2.0)]
    runner, fired, _ = _make(settings, steps)
    n = await runner.run()
    assert n == 0
