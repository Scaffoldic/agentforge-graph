"""feat-009 chunk 2 — churn/authorship denormalised onto node attrs end-to-end.

A full index (temporal on) mines the tree and writes ``introduced/last_changed/
churn_*/top_authors`` onto each symbol's ``attrs`` and into the sidecar
``aggregates`` table; ``ckg_symbol`` then surfaces them for free. Temporal off
leaves attrs clean.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agentforge_graph.core import GraphQuery, NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.temporal import TemporalStore

_CFG_ON = "store:\n  path: .ckg\ntemporal:\n  enabled: true\n"
_CFG_OFF = "store:\n  path: .ckg\ntemporal:\n  enabled: false\n"
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


def _init(repo: Path) -> None:
    repo.mkdir(parents=True)
    _run(repo, "init")


async def _find(cg: CodeGraph, name: str) -> str:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.FUNCTION]))).nodes
    return next(n.id for n in nodes if n.name == name)


async def test_full_index_denormalizes_churn(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init(repo)
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG_ON)

    (repo / "m.py").write_text("def alpha():\n    x = 1\n    return x\n")
    c0 = _commit(repo, "Ann", _TS)
    # a second commit edits alpha so churn accrues to it
    (repo / "m.py").write_text("def alpha():\n    x = 2\n    return x\n")
    c1 = _commit(repo, "Bob", _TS + 3600)

    cg = await CodeGraph.index(repo_path=repo, config=cfg)
    sid = await _find(cg, "alpha")
    node = await cg.store.graph.get(sid)
    await cg.close()

    assert node is not None
    # denormalised onto node attrs (ckg_symbol reads these for free)
    assert node.attrs.get("churn_90d", 0) > 0
    assert node.attrs.get("introduced") == c0
    assert node.attrs.get("last_changed") == c1
    authors = {a["name"] for a in node.attrs.get("top_authors", [])}
    assert authors == {"Ann", "Bob"}

    # and persisted in the sidecar aggregates table
    agg = await TemporalStore.open(repo / ".ckg").aggregate_for(sid)
    assert agg is not None and agg.churn_90d == node.attrs["churn_90d"]


async def test_incremental_refresh_updates_churn(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init(repo)
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG_ON)

    (repo / "m.py").write_text("def alpha():\n    return 1\n")
    _commit(repo, "Ann", _TS)
    cg0 = await CodeGraph.index(repo_path=repo, config=cfg)
    await cg0.close()

    # edit and re-index incrementally → last_changed advances to the new commit
    (repo / "m.py").write_text("def alpha():\n    return 99\n")
    c1 = _commit(repo, "Bob", _TS + 3600)
    cg1 = await CodeGraph.index(repo_path=repo, config=cfg)  # incremental
    sid = await _find(cg1, "alpha")
    node = await cg1.store.graph.get(sid)
    await cg1.close()

    assert node is not None
    assert node.attrs.get("last_changed") == c1
    assert "Bob" in {a["name"] for a in node.attrs.get("top_authors", [])}


async def test_temporal_off_leaves_attrs_clean(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init(repo)
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG_OFF)
    (repo / "m.py").write_text("def alpha():\n    return 1\n")
    _commit(repo, "Ann", _TS)
    cg = await CodeGraph.index(repo_path=repo, config=cfg)
    sid = await _find(cg, "alpha")
    node = await cg.store.graph.get(sid)
    await cg.close()
    assert node is not None
    assert "churn_90d" not in node.attrs
    assert "introduced" not in node.attrs
