"""feat-009 chunk 3 — history / changed_since end-to-end through the real index
path, the serve engine + ckg_history tool, and the CLI."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from agentforge_graph.cli import main
from agentforge_graph.core import GraphQuery, NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.engine import _Engine
from agentforge_graph.serve.tools import CkgHistory, CkgStatus

_CFG = "store:\n  path: .ckg\ntemporal:\n  enabled: true\n"
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


async def _find(cg: CodeGraph, name: str) -> str:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.FUNCTION]))).nodes
    return next(n.id for n in nodes if n.name == name)


async def _setup(tmp_path: Path) -> tuple[Path, str, str, str]:
    """A repo where alpha is introduced at c0 and edited at c1; returns
    (repo, cfg_path, c0, c1)."""
    repo = tmp_path / "proj"
    repo.mkdir()
    _run(repo, "init")
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG)

    (repo / "m.py").write_text("def alpha():\n    return 1\n")
    c0 = _commit(repo, "Ann", _TS)
    cg = await CodeGraph.index(repo_path=repo, config=cfg)  # full → seeds OPENED + mines
    await cg.close()

    (repo / "m.py").write_text("def alpha():\n    return 99\n")
    c1 = _commit(repo, "Bob", _TS + 3600)
    cg = await CodeGraph.index(repo_path=repo, config=cfg)  # incremental
    await cg.close()
    return repo, str(cfg), c0, c1


async def test_codegraph_history_and_changed_since(tmp_path: Path) -> None:
    repo, cfg, c0, c1 = await _setup(tmp_path)
    cg = await CodeGraph.open(repo_path=repo, config=cfg)
    sid = await _find(cg, "alpha")
    try:
        hist = await cg.history(sid)
        # introduced anchored at the full-index commit's OPENED event
        assert hist is not None
        assert hist.introduced == c0
        assert hist.last_changed == c1
        assert hist.churn_90d > 0

        # alpha was modified after c0 → shows up in changed_since(c0)
        changed = await cg.changed_since(c0)
        assert sid in {c.symbol_id for c in changed}
        # nothing changed strictly after c1 (HEAD)
        assert await cg.changed_since(c1) == []

        status = await cg.temporal_status()
        assert status["enabled"] and status["events"] >= 1 and status["has_sidecar"]
    finally:
        await cg.close()


async def test_engine_and_tools(tmp_path: Path) -> None:
    repo, cfg, c0, c1 = await _setup(tmp_path)
    eng = _Engine(repo, cfg)
    try:
        sid = await _find(await eng.code_graph(), "alpha")
        hist = json.loads(await CkgHistory(eng).run(symbol_id=sid))
        assert hist["symbol_id"] == sid
        assert hist["introduced"] == c0 and hist["last_changed"] == c1
        assert "indexed_commit" in hist  # staleness envelope
        assert hist["tool_api_version"]

        status = json.loads(await CkgStatus(eng).run())
        assert status["temporal"]["enabled"] is True
        assert status["temporal"]["events"] >= 1
    finally:
        await eng.close()


def test_cli_history_changed_since_status(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    import asyncio

    repo, cfg, c0, c1 = asyncio.run(_setup(tmp_path))
    sid = asyncio.run(_sid(repo, cfg))

    assert main(["history", sid, "--path", str(repo), "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "introduced:" in out and c0[:10] in out

    assert main(["changed-since", c0, "--path", str(repo), "--config", cfg]) == 0
    out = capsys.readouterr().out
    assert "alpha()." in out

    assert main(["status", "--path", str(repo), "--config", cfg]) == 0
    assert "temporal:       on —" in capsys.readouterr().out


async def _sid(repo: Path, cfg: str) -> str:
    cg = await CodeGraph.open(repo_path=repo, config=cfg)
    try:
        return await _find(cg, "alpha")
    finally:
        await cg.close()
