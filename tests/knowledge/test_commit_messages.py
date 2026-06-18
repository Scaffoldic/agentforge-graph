"""feat-010 follow-up: meaningful git commit messages (conventional commits or
issue refs) become DocChunks that DESCRIBES the in-repo files they touched. Noise
commits are skipped; re-index is idempotent (keyed by sha)."""

from __future__ import annotations

import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.knowledge.commits import _qualifies

_CONFIG = "knowledge:\n  enabled: on\n  commit_messages: on\n"


def test_qualifies_conventional_and_issue_refs() -> None:
    assert _qualifies("feat: add login")
    assert _qualifies("fix(auth): handle empty token")
    assert _qualifies("refactor!: drop legacy path")
    assert _qualifies("Closes #123 in the parser")
    assert _qualifies("PROJ-45 wire up billing")
    assert not _qualifies("wip")
    assert not _qualifies("updated stuff")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
async def repo_cg(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "T")
    (repo / "ckg.yaml").write_text(_CONFIG)
    (repo / "src" / "auth.py").write_text("def login():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "feat(auth): add login")  # qualifies
    (repo / "src" / "auth.py").write_text("def login():\n    return 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "wip messing around")  # noise → skipped
    (repo / "src" / "auth.py").write_text("def login():\n    return 3\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "fix: correct return value, closes #7")  # qualifies
    cg = await CodeGraph.index(repo_path=repo, config=repo / "ckg.yaml")
    try:
        yield cg, repo
    finally:
        await cg.close()


async def _commit_chunks(cg: CodeGraph) -> list[object]:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=999))).nodes
    return [n for n in nodes if n.attrs.get("doc_source") == "commit"]


async def test_qualifying_commits_ingested_with_describes(repo_cg: tuple[CodeGraph, Path]) -> None:
    cg, _ = repo_cg
    assert cg.stats().commits_indexed == 2  # the two qualifying commits, not the wip
    chunks = await _commit_chunks(cg)
    assert {c.attrs.get("text") for c in chunks} == {
        "feat(auth): add login",
        "fix: correct return value, closes #7",
    }
    # each DESCRIBES the touched file (src/auth.py)
    for c in chunks:
        targets = {
            SymbolID.parse(e.dst).path
            for e in await cg.store.graph.adjacent(c.id, [EdgeKind.DESCRIBES], "out")
        }
        assert "src/auth.py" in targets


async def test_reindex_is_idempotent(repo_cg: tuple[CodeGraph, Path]) -> None:
    cg, repo = repo_cg
    before = len(await _commit_chunks(cg))
    await cg.refresh()  # re-runs the knowledge/commit pass
    after = len(await _commit_chunks(cg))
    assert before == after == 2  # shas already present → no duplicates


async def test_off_by_default(tmp_path: Path) -> None:
    repo = tmp_path / "proj2"
    (repo / "src").mkdir(parents=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t.co")
    _git(repo, "config", "user.name", "T")
    (repo / "src" / "m.py").write_text("def f():\n    return 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "feat: thing")
    cg = await CodeGraph.index(repo_path=repo)  # no config → commit_messages off
    try:
        assert cg.stats().commits_indexed == 0
        assert await _commit_chunks(cg) == []
    finally:
        await cg.close()
