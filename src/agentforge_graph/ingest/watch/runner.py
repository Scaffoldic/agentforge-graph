"""feat-014: the watch loop and its static status reader.

``WatchRunner`` is the thin adapter that turns real time + real file events into
calls on the pure :class:`~agentforge_graph.ingest.watch.policy.TriggerPolicy`.
It is constructed with injectable dependencies — a ``pull`` coroutine (the event
source), a ``refresh`` coroutine, a ``now`` clock, and a ``branch_of`` reader —
so the whole loop is unit-tested with a scripted event stream, a fake refresh and
a fake clock: no filesystem, no ``watchfiles``, no sleeping.

``run_watch`` is the real wiring the CLI uses; ``status`` powers ``--status``.
Framework-free (ADR-0001).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from .gitwatch import branch_active, current_branch
from .policy import Event, EventKind, TriggerPolicy, WatchSettings


class WatchStopped(Exception):
    """Raised by a ``pull`` to end the loop cleanly (Ctrl-C in real use, an
    exhausted script in tests)."""


# Types: pull(timeout|None) -> Event|None (None = the timeout elapsed with no
# event); refresh() -> anything (the IndexReport, opaque to the loop).
Pull = Callable[[float | None], Awaitable[Event | None]]
Refresh = Callable[[], Awaitable[object]]
Now = Callable[[], float]


class WatchRunner:
    def __init__(
        self,
        settings: WatchSettings,
        *,
        pull: Pull,
        refresh: Refresh,
        branch_of: Callable[[], str] = lambda: "",
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        now: Now = time.monotonic,
        on_refresh: Callable[[object], None] | None = None,
        on_gate: Callable[[bool, str], None] | None = None,
    ) -> None:
        self.settings = settings
        self.policy = TriggerPolicy(settings, now=now())
        self._pull = pull
        self._refresh = refresh
        self._branch_of = branch_of
        self._include = include if include is not None else ["*"]
        self._exclude = exclude if exclude is not None else []
        self._now = now
        self._on_refresh = on_refresh
        self._on_gate = on_gate
        self.refreshes = 0  # count (tests / status)

    def _active(self) -> bool:
        return branch_active(self._branch_of(), self._include, self._exclude)

    async def run(self) -> int:
        """Loop until the ``pull`` source ends (``WatchStopped``). Returns the
        number of refreshes performed."""
        active = self._active()
        if self._on_gate:
            self._on_gate(active, self._branch_of())
        try:
            while True:
                timeout = self.policy.next_due_in(self._now()) if active else None
                ev = await self._pull(timeout)
                t = self._now()
                if ev is not None and ev.kind is EventKind.GIT:
                    # a branch switch can flip the gate; re-evaluate on git events
                    was, active = active, self._active()
                    if self._on_gate and active != was:
                        self._on_gate(active, self._branch_of())
                if active and ev is not None:
                    self.policy.observe(ev, t)
                if active and self.policy.due(t):
                    await self._do_refresh()
        except WatchStopped:
            return self.refreshes
        return self.refreshes

    async def _do_refresh(self) -> None:
        # Single-flight: the loop awaits the refresh, so events arriving during it
        # are buffered by the source and observed on the next pull.
        report = await self._refresh()
        self.refreshes += 1
        self.policy.reset(self._now())
        if self._on_refresh:
            self._on_refresh(report)


async def _build_refresh(cg: object, *, embed_on_watch: bool, enrich_on_watch: bool) -> Refresh:
    """A refresh coroutine over an already-open ``CodeGraph``: structural
    ``refresh()`` always; embeddings/enrichment only when explicitly enabled
    (watch stays cheap by default — feat-014 §4.3)."""

    async def _refresh() -> object:
        report = await cg.refresh()  # type: ignore[attr-defined]
        if embed_on_watch:
            await cg.embed(only_dirty=True)  # type: ignore[attr-defined]
        if enrich_on_watch:
            await cg.enrich()  # type: ignore[attr-defined]
        return report

    return _refresh


async def run_watch(
    repo: str | Path,
    config: str | None,
    settings: WatchSettings,
    *,
    include: list[str],
    exclude: list[str],
    extra_ignore: list[str],
    embed_on_watch: bool = False,
    enrich_on_watch: bool = False,
    on_refresh: Callable[[object], None] | None = None,
    on_gate: Callable[[bool, str], None] | None = None,
) -> int:
    """Open the repo once, watch it, and refresh on the configured trigger until
    interrupted. Returns the number of refreshes performed. The caller must have
    already run the guard (:func:`.guard.ensure_watchable`)."""
    from agentforge_graph.ingest import CodeGraph

    from ..codegraph import _source_registry
    from .filter import WatchFilter
    from .source import WatchfilesSource

    _source, registry = _source_registry(str(repo), config, None)
    wfilter = WatchFilter(registry, extra_ignore=extra_ignore)
    source = WatchfilesSource(repo, wfilter)
    source.start()
    cg = await CodeGraph.open(repo_path=str(repo), config=config)
    try:
        refresh = await _build_refresh(
            cg, embed_on_watch=embed_on_watch, enrich_on_watch=enrich_on_watch
        )
        runner = WatchRunner(
            settings,
            pull=source.pull,
            refresh=refresh,
            branch_of=lambda: current_branch(repo),
            include=include,
            exclude=exclude,
            on_refresh=on_refresh,
            on_gate=on_gate,
        )
        return await runner.run()
    finally:
        await source.aclose()
        await cg.close()


async def run_once(
    repo: str | Path,
    config: str | None,
    *,
    embed: bool = False,
    enrich: bool = False,
) -> object:
    """One refresh (+ optional embed/enrich), then return the report — the
    ``--once`` path. No watcher is constructed."""
    from agentforge_graph.ingest import CodeGraph

    cg = await CodeGraph.open(repo_path=str(repo), config=config)
    try:
        report = await cg.refresh()
        if embed:
            await cg.embed(only_dirty=True)
        if enrich:
            await cg.enrich()
        return report
    finally:
        await cg.close()


@dataclass
class WatchStatus:
    trigger: str
    store_root: str
    indexed_commit: str
    head_commit: str
    dirty: bool
    branch: str
    active: bool
    central: bool
    read_only: bool

    def render(self) -> str:
        lines = [
            f"trigger:        {self.trigger}",
            f"store:          {self.store_root}"
            + (" (central)" if self.central else "")
            + (" (read-only)" if self.read_only else ""),
            f"branch:         {self.branch or '(detached / no git)'}",
            f"watch active:   {'yes' if self.active else 'no — branch gated out'}",
            f"indexed commit: {self.indexed_commit or '(none)'}",
            f"head commit:    {self.head_commit or '(not a git repo)'}",
            f"dirty:          {'yes — a refresh would re-index' if self.dirty else 'no'}",
        ]
        return "\n".join(lines)


def status(repo: str | Path, config: str | None, settings: WatchSettings) -> WatchStatus:
    """Static status — no running watcher needed (no IPC). Reads the feat-004
    ``IndexMeta`` (indexed commit) + git HEAD to report freshness, and the
    ``watch.branches`` gate to report whether watch would run on this branch."""
    from agentforge_graph.config import StoreConfig, WatchConfig, resolve_config
    from agentforge_graph.ingest.codegraph import _git_commit
    from agentforge_graph.ingest.incremental import IndexMeta
    from agentforge_graph.store import resolve_root

    cfg = resolve_config(config, str(repo))
    store_cfg = StoreConfig.load(cfg)
    watch_cfg = WatchConfig.load(cfg)
    root = resolve_root(str(repo), store_cfg)
    meta = IndexMeta.load(root)
    head = _git_commit(repo)
    branch = current_branch(repo)
    dirty = bool(head) and bool(meta.indexed_commit) and head != meta.indexed_commit
    return WatchStatus(
        trigger=settings.trigger,
        store_root=str(root),
        indexed_commit=meta.indexed_commit,
        head_commit=head,
        dirty=dirty,
        branch=branch,
        active=branch_active(branch, watch_cfg.branches.include, watch_cfg.branches.exclude),
        central=bool(store_cfg.central_root),
        read_only=store_cfg.read_only,
    )
