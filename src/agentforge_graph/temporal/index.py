"""``TemporalIndex`` — the read side of the evolution log (feat-009 chunk 3).

Answers the questions an agent asks after a regression — *when was this
introduced, who owns it, how much does it churn, what changed since <ref>* —
from the sidecar (``TemporalStore``) plus the current graph (for the live
span/path). Pure reads; no mutation, no embedding. ``as_of`` reconstruction
lands in chunk 5.

`introduced` prefers the chunk-1 ``OPENED`` event (the exact birth commit when
the symbol was added during the temporal era) and falls back to the mined
aggregate's window-bounded estimate otherwise (design §4.5 known limitation).
"""

from __future__ import annotations

import subprocess
from fnmatch import fnmatch

from agentforge_graph.core import GraphStore, SymbolID

from .events import Author, Change, EventKind, SymbolHistory
from .store import TemporalStore


class TemporalIndex:
    def __init__(self, store: TemporalStore, graph: GraphStore, repo_root: str = "") -> None:
        self._store = store
        self._graph = graph
        self._root = repo_root

    async def history(self, symbol_id: str) -> SymbolHistory:
        events = await self._store.events_for(symbol_id)
        agg = await self._store.aggregate_for(symbol_id)

        # introduced: earliest OPENED event (exact) wins over the mined estimate.
        opened = [e for e in events if e.event is EventKind.OPENED]
        if opened:
            first = min(opened, key=lambda e: e.ts)
            introduced, introduced_ts = first.commit, first.ts
        elif agg is not None:
            introduced, introduced_ts = agg.introduced_sha, agg.introduced_ts
        else:
            introduced, introduced_ts = "", 0

        # last_changed: the most recent of any event or the mined last_changed.
        last, last_ts = "", 0
        for e in events:
            if e.ts >= last_ts:
                last, last_ts = e.commit, e.ts
        if agg is not None and agg.last_changed_ts >= last_ts:
            last, last_ts = agg.last_changed_sha, agg.last_changed_ts

        authors = [Author(name=n, commits=c) for n, c in (agg.top_authors if agg else [])]
        return SymbolHistory(
            symbol_id=symbol_id,
            introduced=introduced,
            introduced_ts=introduced_ts,
            last_changed=last,
            last_changed_ts=last_ts,
            churn_30d=agg.churn_30d if agg else 0,
            churn_90d=agg.churn_90d if agg else 0,
            authors=authors,
            events=events,
        )

    async def authors(self, symbol_id: str) -> list[Author]:
        agg = await self._store.aggregate_for(symbol_id)
        return [Author(name=n, commits=c) for n, c in (agg.top_authors if agg else [])]

    async def churn(self, symbol_id: str, window_days: int = 90) -> int:
        agg = await self._store.aggregate_for(symbol_id)
        if agg is None:
            return 0
        return agg.churn_30d if window_days <= 30 else agg.churn_90d

    async def changed_since(self, ref: str, scope: str | None = None) -> list[Change]:
        """Symbols with recorded activity after ``ref`` (a commit-ish), newest
        first. Lifecycle events (opened/closed) and mined modifications both
        count; ``scope`` keeps only paths matching the glob or prefix."""
        since_ts = self._resolve_ts(ref)
        changes: dict[str, Change] = {}
        # lifecycle events after the ref — the precise kind
        for e in await self._store.all_events():
            if e.ts > since_ts:
                changes[e.symbol_id] = Change(
                    symbol_id=e.symbol_id,
                    path=SymbolID.parse(e.symbol_id).path,
                    kind=e.event.value,
                    commit=e.commit,
                    ts=e.ts,
                )
        # mined modifications after the ref (don't overwrite a precise lifecycle)
        for agg in await self._store.all_aggregates():
            if agg.last_changed_ts > since_ts and agg.symbol_id not in changes:
                changes[agg.symbol_id] = Change(
                    symbol_id=agg.symbol_id,
                    path=SymbolID.parse(agg.symbol_id).path,
                    kind="modified",
                    commit=agg.last_changed_sha,
                    ts=agg.last_changed_ts,
                )
        out = [c for c in changes.values() if _in_scope(c.path, scope)]
        out.sort(key=lambda c: (-c.ts, c.symbol_id))
        return out

    # --- internals --------------------------------------------------------

    def _resolve_ts(self, ref: str) -> int:
        """Author time (epoch s) of ``ref``. Accepts a raw epoch int too, so the
        API is testable without a working tree."""
        if ref.isdigit():
            return int(ref)
        try:
            out = subprocess.run(
                ["git", "-C", self._root, "show", "-s", "--format=%ct", ref],
                capture_output=True,
                text=True,
                check=True,
            )
            return int(out.stdout.strip())
        except (subprocess.SubprocessError, OSError, ValueError) as exc:
            raise ValueError(f"cannot resolve ref {ref!r} to a commit time") from exc


def _in_scope(path: str, scope: str | None) -> bool:
    if not scope:
        return True
    return path.startswith(scope) or fnmatch(path, scope)
