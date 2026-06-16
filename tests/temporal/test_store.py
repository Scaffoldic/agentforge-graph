"""feat-009 chunk 1 — the TemporalStore sidecar + recorder (append-only,
idempotent, prunable)."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.temporal import Event, EventKind, TemporalStore, build_recorder


async def test_record_and_read_back(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    assert (tmp_path / "temporal.db").exists()
    await store.record(
        [
            Event(symbol_id="s1", event=EventKind.OPENED, commit="c0", ts=10),
            Event(symbol_id="s2", event=EventKind.OPENED, commit="c0", ts=10),
            Event(symbol_id="s1", event=EventKind.CLOSED, commit="c1", ts=20),
        ]
    )
    s1 = await store.events_for("s1")
    assert [(e.event, e.commit) for e in s1] == [
        (EventKind.OPENED, "c0"),
        (EventKind.CLOSED, "c1"),
    ]
    assert len(await store.all_events()) == 3


async def test_record_is_idempotent(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    ev = Event(symbol_id="s1", event=EventKind.OPENED, commit="c0", ts=10)
    assert await store.record([ev]) == 1
    assert await store.record([ev]) == 0  # same (symbol, commit, event) → ignored
    assert len(await store.all_events()) == 1


async def test_prune_drops_old_closed_keeps_opened(tmp_path: Path) -> None:
    store = TemporalStore.open(tmp_path)
    await store.record(
        [
            Event(symbol_id="s1", event=EventKind.OPENED, commit="c0", ts=10),
            Event(symbol_id="s1", event=EventKind.CLOSED, commit="c1", ts=20),
            Event(symbol_id="s2", event=EventKind.CLOSED, commit="c2", ts=100),
        ]
    )
    removed = await store.prune(before_ts=50)
    assert removed == 1  # the ts=20 close
    kinds = {(e.symbol_id, e.event) for e in await store.all_events()}
    assert (("s1", EventKind.OPENED)) in kinds  # opened anchors 'introduced' — kept
    assert (("s2", EventKind.CLOSED)) in kinds  # newer than horizon — kept


async def test_recorder_buffers_and_flushes_once(tmp_path: Path) -> None:
    rec = build_recorder(str(tmp_path))
    rec.open(["a", "b"], "c0", 10)
    rec.close(["x"], "c0", 10)
    assert await rec._store.all_events() == []  # nothing written until flush
    await rec.flush()
    evs = {(e.symbol_id, e.event) for e in await rec._store.all_events()}
    assert evs == {("a", EventKind.OPENED), ("b", EventKind.OPENED), ("x", EventKind.CLOSED)}
