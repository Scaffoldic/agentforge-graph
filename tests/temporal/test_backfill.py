"""feat-009 chunk 4 — history backfill (``ckg index --history N``).

Indexing only at HEAD anchors every symbol's ``introduced`` at the index commit.
Backfill replays history into a throwaway store so the earliest ``OPENED`` event
becomes the symbol's *true* introduction commit, and symbols deleted before HEAD
get their ``OPENED``/``CLOSED`` recorded — without touching the HEAD graph.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agentforge_graph.cli import main
from agentforge_graph.core import GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.temporal import EventKind, TemporalStore, parse_history, run_backfill

_CFG = "store:\n  path: .ckg\ntemporal:\n  enabled: true\n"
_OFF = "store:\n  path: .ckg\ntemporal:\n  enabled: false\n"
_TS = 1_750_000_000


def _run(repo: Path, *args: str, author: str | None = None, ts: int | None = None) -> str:
    env = dict(os.environ)
    if author:
        env |= {
            "GIT_AUTHOR_NAME": author,
            "GIT_AUTHOR_EMAIL": f"{author}@t",
            "GIT_COMMITTER_NAME": author,
            "GIT_COMMITTER_EMAIL": f"{author}@t",
        }
    if ts is not None:
        env |= {"GIT_AUTHOR_DATE": f"{ts} +0000", "GIT_COMMITTER_DATE": f"{ts} +0000"}
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _commit(repo: Path, author: str, ts: int) -> str:
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "c", author=author, ts=ts)
    return _run(repo, "rev-parse", "HEAD")


async def _history_repo(tmp_path: Path, cfg_text: str = _CFG) -> tuple[Path, str, dict[str, str]]:
    """alpha@c0; +beta +gone.py@c1; -gone.py +edit alpha@c2. Indexed at HEAD only."""
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    _run(repo, "init")
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(cfg_text)
    m = repo / "m.py"

    m.write_text("def alpha():\n    return 1\n")
    c0 = _commit(repo, "Ann", _TS)
    m.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    (repo / "gone.py").write_text("def doomed():\n    return 0\n")
    c1 = _commit(repo, "Bob", _TS + 3600)
    m.write_text("def alpha():\n    return 11\n\n\ndef beta():\n    return 2\n")
    (repo / "gone.py").unlink()
    c2 = _commit(repo, "Carol", _TS + 7200)

    cg = await CodeGraph.index(repo_path=repo, config=cfg)  # full index at HEAD only
    await cg.close()
    return repo, str(cfg), {"c0": c0, "c1": c1, "c2": c2}


async def _find(cg: CodeGraph, name: str) -> str:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.FUNCTION]))).nodes
    return next(n.id for n in nodes if n.name == name)


def test_parse_history() -> None:
    assert parse_history("full") == -1
    assert parse_history("5") == 5
    assert parse_history(3) == 3
    assert parse_history(None) == 0
    assert parse_history("garbage") == 0


async def test_backfill_anchors_true_introduction(tmp_path: Path) -> None:
    repo, cfg, sha = await _history_repo(tmp_path)

    cg = await CodeGraph.open(repo_path=repo, config=cfg)
    alpha = await _find(cg, "alpha")
    beta = await _find(cg, "beta")
    # before backfill: HEAD-only index anchors everything at the index commit
    assert (await cg.history(alpha)).introduced == sha["c2"]
    await cg.close()

    rep = await run_backfill(repo, cfg, parse_history("full"))
    assert rep.ran and rep.commits == 3 and rep.backfilled_through == sha["c0"]
    assert rep.events_added > 0

    cg = await CodeGraph.open(repo_path=repo, config=cfg)
    try:
        # earliest OPENED is now the real birth commit
        assert (await cg.history(alpha)).introduced == sha["c0"]
        assert (await cg.history(beta)).introduced == sha["c1"]
        ts = await cg.temporal_status()
        assert ts["backfilled_through"] == sha["c0"]
    finally:
        await cg.close()

    # the symbol deleted before HEAD got OPENED@c1 + CLOSED@c2 — though it is
    # absent from the current graph
    store = TemporalStore.open(repo / ".ckg")
    doomed = next(
        e.symbol_id
        for e in await store.all_events()
        if SymbolID.parse(e.symbol_id).descriptor == "doomed()."
    )
    kinds = {e.event for e in await store.events_for(doomed)}
    assert EventKind.OPENED in kinds and EventKind.CLOSED in kinds
    assert await cg_absent(repo, cfg, doomed)


async def cg_absent(repo: Path, cfg: str, symbol_id: str) -> bool:
    cg = await CodeGraph.open(repo_path=repo, config=cfg)
    try:
        return (await cg.store.graph.get(symbol_id)) is None
    finally:
        await cg.close()


async def test_backfill_is_resumable_noop(tmp_path: Path) -> None:
    repo, cfg, _ = await _history_repo(tmp_path)
    first = await run_backfill(repo, cfg, parse_history("full"))
    assert first.ran
    again = await run_backfill(repo, cfg, parse_history("full"))
    assert not again.ran and again.reason == "already backfilled"


async def test_backfill_skips_when_disabled_or_zero(tmp_path: Path) -> None:
    repo, cfg, _ = await _history_repo(tmp_path, cfg_text=_OFF)
    off = await run_backfill(repo, cfg, parse_history("full"))
    assert not off.ran and off.reason == "temporal disabled"
    repo2, cfg2, _ = await _history_repo(tmp_path / "x")
    zero = await run_backfill(repo2, cfg2, 0)
    assert not zero.ran


def test_cli_index_history_and_status(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    repo, cfg, _ = asyncio.run(_history_repo(tmp_path))
    assert main(["index", "--path", str(repo), "--config", cfg, "--history", "full"]) == 0
    out = capsys.readouterr().out
    assert "backfill: replayed" in out

    assert main(["status", "--path", str(repo), "--config", cfg]) == 0
    assert "history back to" in capsys.readouterr().out
