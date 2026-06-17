"""feat-009 chunk 5 — as_of reconstruction + retention horizon.

The headline property: after backfilling history, the set of symbols
``alive_at(C)`` reconstructed from the log equals the symbols a *full index at
C* would produce — for every backfilled commit (the feat-004 equivalence,
per commit). Plus: a commit beyond the retention horizon raises rather than
answering wrong, and as_of retrieval drops symbols added after the commit.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from agentforge_graph.config import DEFAULT_EXCLUDES
from agentforge_graph.core import GraphQuery, NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.ingest.packs import builtin_registry
from agentforge_graph.ingest.pipeline import IngestPipeline
from agentforge_graph.temporal import TemporalError, TemporalIndex, TemporalStore, run_backfill
from agentforge_graph.temporal.backfill import GitBlobSource, _open_temp_store

_CFG = "store:\n  path: .ckg\nembed:\n  driver: fake\n  dim: 16\ntemporal:\n  enabled: true\n"
_TS = 1_750_000_000
_SYMBOLS = [NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD]


def _run(repo: Path, *args: str, author: str = "Ann", ts: int | None = None) -> str:
    env = dict(os.environ) | {
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


def _commit(repo: Path, ts: int) -> str:
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", "c", ts=ts)
    return _run(repo, "rev-parse", "HEAD")


async def _build(tmp_path: Path) -> tuple[Path, str, dict[str, str]]:
    repo = tmp_path / "proj"
    repo.mkdir(parents=True)
    _run(repo, "init")
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG)
    m = repo / "m.py"

    m.write_text("def alpha():\n    return 1\n")
    c0 = _commit(repo, _TS)
    m.write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    (repo / "gone.py").write_text("def doomed():\n    return 0\n")
    c1 = _commit(repo, _TS + 3600)
    m.write_text("def alpha():\n    return 9\n\n\ndef beta():\n    return 2\n")
    (repo / "gone.py").unlink()
    c2 = _commit(repo, _TS + 7200)

    cg = await CodeGraph.index(repo_path=repo, config=cfg)
    await cg.close()
    await run_backfill(repo, str(cfg), -1)  # full backfill
    return repo, str(cfg), {"c0": c0, "c1": c1, "c2": c2}


async def _symbols_at(repo: Path, commit: str) -> set[str]:
    """The code-symbol ids a *full index at ``commit``* would produce (built
    from git-blob content into a throwaway store) — the equivalence oracle."""
    registry = builtin_registry()
    with tempfile.TemporaryDirectory() as tmp:
        store = await _open_temp_store(Path(tmp))
        try:
            src = GitBlobSource(repo, commit, exclude=list(DEFAULT_EXCLUDES))
            await IngestPipeline(repo=repo.resolve().name, commit=commit).run(
                src, store.graph, registry
            )
            nodes = (await store.graph.query(GraphQuery(kinds=_SYMBOLS, limit=10_000_000))).nodes
            return {n.id for n in nodes}
        finally:
            await store.close()


def _ti(repo: Path, retention: int = 0) -> TemporalIndex:
    return TemporalIndex(
        TemporalStore.open(repo / ".ckg"),
        graph=None,  # type: ignore[arg-type]
        repo_root=str(repo),
        retention_commits=retention,
    )


async def test_alive_at_equals_full_index_per_commit(tmp_path: Path) -> None:
    repo, _cfg, sha = await _build(tmp_path)
    ti = _ti(repo)
    for name in ("c0", "c1", "c2"):
        reconstructed = await ti.alive_at(sha[name])
        oracle = await _symbols_at(repo, sha[name])
        assert reconstructed == oracle, name


async def test_beyond_retention_horizon_raises(tmp_path: Path) -> None:
    repo, _cfg, sha = await _build(tmp_path)
    ti = _ti(repo, retention=1)  # horizon = HEAD~1 = c1
    assert await ti.alive_at(sha["c1"])  # at the horizon: allowed
    with pytest.raises(TemporalError):
        await ti.alive_at(sha["c0"])  # older than the horizon: refused


async def test_as_of_retrieval_drops_later_symbols(tmp_path: Path) -> None:
    repo, cfg, sha = await _build(tmp_path)
    cg = await CodeGraph.open(repo_path=repo, config=cfg)
    try:
        nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.FUNCTION]))).nodes
        beta = next(n.id for n in nodes if n.name == "beta")
        alpha = next(n.id for n in nodes if n.name == "alpha")

        # beta was introduced at c1 → absent as_of c0, present as_of c1
        pack0 = await cg.retrieve(symbol=beta, mode="definition", as_of=sha["c0"])
        assert beta not in {it.id for it in pack0.items}
        pack1 = await cg.retrieve(symbol=beta, mode="definition", as_of=sha["c1"])
        assert beta in {it.id for it in pack1.items}
        # alpha existed at c0 → present
        packa = await cg.retrieve(symbol=alpha, mode="definition", as_of=sha["c0"])
        assert alpha in {it.id for it in packa.items}
    finally:
        await cg.close()
