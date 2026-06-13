"""feat-010 end-to-end: index a repo with ADRs → Decision/GOVERNS/SUPERSEDES in
the graph, decisions(), retrieval surfacing, incrementality, ckg_decisions tool,
ckg decisions CLI, and the no-ADR negative."""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "repo"


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg, repo
    finally:
        await cg.close()


async def test_decisions_indexed(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    report = cg.stats()
    assert report.decisions_indexed == 2
    assert report.governs_resolved >= 1  # PaymentService / charge / payments.py
    decisions = await cg.decisions()
    by_adr = {d.adr_id: d for d in decisions}
    assert by_adr["ADR-0012"].status == "accepted"
    assert by_adr["ADR-0012"].date == "2025-11-03"
    assert by_adr["ADR-0007"].status == "superseded"


async def test_governs_and_supersedes_edges(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DECISION], limit=99))).nodes
    d12 = next(n for n in nodes if "0012" in SymbolID.parse(n.id).path)
    governs = await cg.store.graph.adjacent(d12.id, [EdgeKind.GOVERNS], "out")
    governed = {SymbolID.parse(e.dst).descriptor for e in governs}
    assert "PaymentService#" in governed  # the class, by name mention
    supersedes = await cg.store.graph.adjacent(d12.id, [EdgeKind.SUPERSEDES], "out")
    assert len(supersedes) == 1  # → ADR-0007 (two-round upsert connected it)


async def test_scope_filter(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    scoped = await cg.decisions(scope="src/app/payments.py")
    assert {d.adr_id for d in scoped} == {"ADR-0012"}  # governs a symbol under that path
    assert await cg.decisions(status="accepted") == [
        d for d in await cg.decisions() if d.status == "accepted"
    ]


async def test_retrieval_surfaces_governing_decision(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    cls = next(
        n
        for n in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.CLASS], limit=10))).nodes
        if n.name == "PaymentService"
    )
    pack = await cg.retrieve(symbol=cls.id, mode="context")
    decisions = [it for it in pack.items if it.kind is NodeKind.DECISION]
    assert decisions, "a governed symbol must surface its decision"
    assert "accepted" in (decisions[0].code or "")  # status rendered inline


async def test_incremental_adr_edit_and_delete(graph: tuple[CodeGraph, Path]) -> None:
    cg, repo = graph
    adr = repo / "docs" / "adr" / "0012-idempotency.md"
    adr.write_text(adr.read_text().replace("status: accepted", "status: deprecated"))
    await cg.refresh()
    assert {d.adr_id: d.status for d in await cg.decisions()}["ADR-0012"] == "deprecated"
    # deleting the ADR removes its Decision
    adr.unlink()
    await cg.refresh()
    assert "ADR-0012" not in {d.adr_id for d in await cg.decisions()}


async def test_ckg_decisions_tool(graph: tuple[CodeGraph, Path]) -> None:
    from agentforge_graph.serve.engine import _Engine
    from agentforge_graph.serve.tools import CkgDecisions

    _, repo = graph
    out = json.loads(await CkgDecisions(_Engine(repo)).run(status="accepted"))
    assert out["count"] == 1
    assert out["decisions"][0]["adr_id"] == "ADR-0012"
    assert "indexed_commit" in out


def test_ckg_decisions_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "decisions: 2 ADRs" in out
    assert main(["decisions", str(repo)]) == 0
    listing = capsys.readouterr().out
    assert "ADR-0012" in listing and "accepted" in listing


async def test_no_adr_repo(tmp_path: Path) -> None:
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        assert cg.stats().decisions_indexed == 0
        assert await cg.decisions() == []
    finally:
        await cg.close()
