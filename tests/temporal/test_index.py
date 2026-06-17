"""feat-009 chunk 3 — ``TemporalIndex`` read APIs over a hand-populated sidecar.

No git/graph needed: events + aggregates are written directly and refs are
passed as raw epoch ints (``_resolve_ts`` accepts digit strings), so the read
logic is tested in isolation.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import SymbolID
from agentforge_graph.temporal import (
    Author,
    Entity,
    Event,
    EventKind,
    SymbolAggregate,
    TemporalIndex,
    TemporalStore,
)

A = SymbolID.for_symbol("py", "repo", "m.py", "alpha().")
B = SymbolID.for_symbol("py", "repo", "m.py", "beta().")
C = SymbolID.for_symbol("py", "repo", "other.py", "gamma().")


def _agg(sid: str, **kw: object) -> SymbolAggregate:
    base: dict = dict(
        symbol_id=sid,
        churn_30d=0,
        churn_90d=0,
        top_authors=[],
        introduced_sha="",
        introduced_ts=0,
        last_changed_sha="",
        last_changed_ts=0,
    )
    base.update(kw)
    return SymbolAggregate(**base)  # type: ignore[arg-type]


def _opened(sid: str, commit: str, ts: int) -> Event:
    return Event(symbol_id=sid, event=EventKind.OPENED, commit=commit, ts=ts, entity=Entity.NODE)


def _index(store: TemporalStore) -> TemporalIndex:
    return TemporalIndex(store, graph=None, repo_root="")  # type: ignore[arg-type]


async def test_history_prefers_opened_event_for_introduced(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    await store.record([_opened(A, "c0", 100)])
    await store.upsert_aggregates(
        [
            _agg(
                A,
                introduced_sha="mined",
                introduced_ts=90,
                last_changed_sha="cY",
                last_changed_ts=200,
                churn_30d=3,
                churn_90d=7,
                top_authors=[("Ann", 2)],
            ),
        ]
    )
    hist = await _index(store).history(A)
    # the exact OPENED event wins over the window-bounded mined estimate
    assert hist.introduced == "c0" and hist.introduced_ts == 100
    assert hist.last_changed == "cY" and hist.last_changed_ts == 200
    assert hist.churn_30d == 3 and hist.churn_90d == 7
    assert hist.authors == [Author(name="Ann", commits=2)]
    assert len(hist.events) == 1


async def test_history_falls_back_to_aggregate(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    await store.upsert_aggregates([_agg(A, introduced_sha="mined", introduced_ts=90)])
    hist = await _index(store).history(A)
    assert hist.introduced == "mined" and hist.introduced_ts == 90


async def test_history_empty_when_unknown(tmp_path: Path) -> None:
    hist = await _index(TemporalStore.open(tmp_path)).history(A)
    assert hist.introduced == "" and hist.churn_90d == 0 and hist.events == []


async def test_churn_picks_window(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    await store.upsert_aggregates([_agg(A, churn_30d=3, churn_90d=7)])
    ti = _index(store)
    assert await ti.churn(A, 30) == 3
    assert await ti.churn(A, 90) == 7
    assert await ti.churn(A, 365) == 7  # >90d clamps to the 90d window
    assert await ti.churn(B, 30) == 0  # unknown symbol


async def test_changed_since_filters_and_orders(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    await store.record([_opened(A, "ca", 100), _opened(B, "cb", 300)])
    await store.upsert_aggregates([_agg(C, last_changed_sha="cc", last_changed_ts=250)])
    ti = _index(store)

    changes = await ti.changed_since("200")
    # A (ts 100) is before the ref; B (300, opened) + C (250, modified) survive,
    # newest first
    assert [c.symbol_id for c in changes] == [B, C]
    assert changes[0].kind == "opened" and changes[1].kind == "modified"

    scoped = await ti.changed_since("200", scope="other.py")
    assert [c.symbol_id for c in scoped] == [C]
