"""feat-014: a REAL end-to-end watch run — actual watchfiles, actual fs events,
actual incremental refresh. Skipped where the optional `watch` extra is not
installed (e.g. CI's base env); exercised locally and anywhere `[watch]` is present.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

pytest.importorskip("watchfiles")

from agentforge_graph.core import GraphQuery, SymbolID  # noqa: E402
from agentforge_graph.ingest import CodeGraph  # noqa: E402
from agentforge_graph.ingest.watch import WatchSettings, run_watch  # noqa: E402


async def _descriptors(repo: Path) -> set[str]:
    cg = await CodeGraph.open(repo_path=str(repo))
    try:
        nodes = (await cg.store.graph.query(GraphQuery(limit=100_000))).nodes
        return {SymbolID.parse(n.id).descriptor for n in nodes}
    finally:
        await cg.close()


async def test_watch_live_refreshes_on_save(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("def alpha():\n    return 1\n")
    cg = await CodeGraph.index(repo_path=str(repo))
    await cg.close()
    assert not any(d.startswith("zeta") for d in await _descriptors(repo))

    got = asyncio.Event()
    settings = WatchSettings(trigger="on-save", debounce_ms=150)
    task = asyncio.create_task(
        run_watch(
            repo,
            None,
            settings,
            include=["*"],
            exclude=[],
            extra_ignore=[],
            on_refresh=lambda _r: got.set(),
        )
    )
    try:
        await asyncio.sleep(0.6)  # let the watcher spin up
        (repo / "pkg" / "added.py").write_text("def zeta():\n    return 9\n")
        await asyncio.wait_for(got.wait(), timeout=10)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    # the new symbol was indexed live by the real fs-watch → refresh path
    assert any(d.startswith("zeta") for d in await _descriptors(repo))
