"""feat-012 end-to-end with ScriptedJudge: CodeGraph.enrich/tagged, dirty
draining, retrieval surfacing, ckg_explain tool, and the ckg enrich/tagged CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.core import GraphQuery, NodeKind, SymbolID
from agentforge_graph.enrich import ScriptedJudge
from agentforge_graph.ingest import CodeGraph

from .conftest import PATTERNS_CODE


async def test_enrich_and_tagged(graph: CodeGraph) -> None:
    report = await graph.enrich(judge=ScriptedJudge())
    assert report.tagged >= 5
    repos = await graph.tagged("Repository")
    assert [SymbolID.parse(t.symbol_id).descriptor for t in repos] == ["OrderRepository#"]
    assert repos[0].confidence >= 0.7 and repos[0].rationale


async def test_tagged_respects_confidence_floor(graph: CodeGraph) -> None:
    from agentforge_graph.enrich import Candidate, Verdict

    def mid(c: Candidate) -> list[Verdict]:
        return [
            Verdict(pattern=p, is_match=True, confidence=0.75, rationale="x") for p in c.patterns
        ]

    await graph.enrich(judge=ScriptedJudge(mid))
    assert await graph.tagged("Repository", min_confidence=0.7)
    assert await graph.tagged("Repository", min_confidence=0.8) == []


async def test_retrieval_surfaces_pattern_tag(graph: CodeGraph) -> None:
    await graph.enrich(judge=ScriptedJudge())
    cls = next(
        n
        for n in (await graph.store.graph.query(GraphQuery(kinds=[NodeKind.CLASS], limit=99))).nodes
        if n.name == "OrderRepository"
    )
    pack = await graph.retrieve(symbol=cls.id, mode="context")
    tags = [it for it in pack.items if it.kind is NodeKind.PATTERN_TAG]
    assert tags and "[llm]" in (tags[0].code or "")
    # opt-out hides them
    bare = await graph.retrieve(symbol=cls.id, mode="context", include_llm_facts=False)
    assert not [it for it in bare.items if it.kind is NodeKind.PATTERN_TAG]


async def test_enrich_drains_dirty(graph: CodeGraph) -> None:
    from agentforge_graph.config import StoreConfig
    from agentforge_graph.ingest.incremental import DirtySet

    root = Path(graph._repo_path) / StoreConfig.load(None).path
    cls = next(
        n
        for n in (await graph.store.graph.query(GraphQuery(kinds=[NodeKind.CLASS], limit=99))).nodes
        if n.name == "WidgetFactory"
    )
    await DirtySet(root).add([cls.id])  # only this symbol is dirty
    report = await graph.enrich(judge=ScriptedJudge())
    assert report.candidates == 1  # scoped to the dirty symbol
    assert await DirtySet(root).dirty_for("patterns") == []  # drained


async def test_ckg_explain_tool(graph: CodeGraph) -> None:
    from agentforge_graph.serve.engine import _Engine
    from agentforge_graph.serve.tools import CkgExplain

    await graph.enrich(judge=ScriptedJudge())
    repo = (await graph.tagged("Repository"))[0]
    out = json.loads(await CkgExplain(_Engine(graph._repo_path)).run(symbol_id=repo.symbol_id))
    assert [t["pattern"] for t in out["tags"]] == ["Repository"]
    assert out["facts"]  # 1-hop typed facts present


def test_ckg_enrich_and_tagged_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Force the CLI's enrich to use the ScriptedJudge (no live model).
    from agentforge_graph.cli import main
    from agentforge_graph.ingest import codegraph

    real_enrich = codegraph.CodeGraph.enrich

    async def fake_enrich(self, judge=None, budget_usd=None):  # type: ignore[no-untyped-def]
        return await real_enrich(self, judge=ScriptedJudge(), budget_usd=budget_usd)

    monkeypatch.setattr(codegraph.CodeGraph, "enrich", fake_enrich)

    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(PATTERNS_CODE)
    # scripted provider: the judge is monkeypatched above; the config must declare
    # it so the ENH-026 preflight doesn't require the (unused) Bedrock extra.
    (repo / "ckg.yaml").write_text("enrich:\n  provider: scripted\n")
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    assert main(["enrich", str(repo)]) == 0
    assert "tagged" in capsys.readouterr().out
    assert main(["tagged", "Repository", str(repo)]) == 0
    assert "OrderRepository" in capsys.readouterr().out
