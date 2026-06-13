"""feat-012 summaries end-to-end via CodeGraph.summarize (fake embedder): repo
map line, ckg_explain prose, retrieval concept→code, dirty draining, CLI."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml

from agentforge_graph.core import GraphQuery, NodeKind
from agentforge_graph.enrich import ScriptedSummarizer
from agentforge_graph.ingest import CodeGraph

CODE = "class OrderService:\n    def place(self, order):\n        return order\n"


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(CODE)
    # fake embedder so summarize() embeds without Bedrock
    (repo / "ckg.yaml").write_text(yaml.safe_dump({"embed": {"driver": "fake", "dim": 8}}))
    cg = await CodeGraph.index(repo_path=repo, config=str(repo / "ckg.yaml"))
    try:
        yield cg, repo
    finally:
        await cg.close()


async def test_summarize_and_list(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    report = await cg.summarize(summarizer=ScriptedSummarizer())
    assert report.files_summarized == 1 and report.repo_summarized
    items = await cg.summaries(level="file")
    assert items and items[0].path == "app.py" and items[0].text


async def test_repo_map_shows_summary_line(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    await cg.summarize(summarizer=ScriptedSummarizer())
    text = await cg.repo_map(budget_tokens=2000)
    assert "# summary of app.py" in text


async def test_ckg_explain_includes_summary(graph: tuple[CodeGraph, Path]) -> None:
    from agentforge_graph.serve.engine import _Engine

    cg, repo = graph
    await cg.summarize(summarizer=ScriptedSummarizer())
    cls = next(
        n.id
        for n in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.CLASS], limit=9))).nodes
    )
    out = await _Engine(repo, str(repo / "ckg.yaml")).explain(cls)
    assert out["summary"]  # the owning file's summary


async def test_retrieval_concept_to_code(graph: tuple[CodeGraph, Path]) -> None:
    # a vector hit on a summary expands via SUMMARIZES to the file it summarizes
    cg, _ = graph
    await cg.summarize(summarizer=ScriptedSummarizer())
    pack = await cg.retrieve(query="summary of app.py (1 symbols)", k=3)
    kinds = {it.kind for it in pack.items}
    assert NodeKind.SUMMARY in kinds  # the summary was retrieved
    assert NodeKind.FILE in kinds  # …and expanded to its file


async def test_summarize_drains_dirty(graph: tuple[CodeGraph, Path]) -> None:
    from agentforge_graph.ingest.incremental import DirtySet

    cg, repo = graph
    root = repo / ".ckg"
    cls = next(
        n for n in (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.CLASS], limit=9))).nodes
    )
    await DirtySet(root).add([cls.id])  # a symbol in app.py is dirty for summaries
    report = await cg.summarize(summarizer=ScriptedSummarizer())
    assert report.files_summarized == 1
    assert await DirtySet(root).dirty_for("summaries") == []  # drained


def test_cli_enrich_summaries_and_list(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentforge_graph.cli import main
    from agentforge_graph.ingest import codegraph

    real = codegraph.CodeGraph.summarize

    async def fake_summarize(self, summarizer=None, budget_usd=None):  # type: ignore[no-untyped-def]
        return await real(self, summarizer=ScriptedSummarizer(), budget_usd=budget_usd)

    monkeypatch.setattr(codegraph.CodeGraph, "summarize", fake_summarize)

    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(CODE)
    (repo / "ckg.yaml").write_text(yaml.safe_dump({"embed": {"driver": "fake", "dim": 8}}))
    cfg = str(repo / "ckg.yaml")
    assert main(["index", str(repo), "--config", cfg]) == 0
    capsys.readouterr()
    assert main(["enrich", str(repo), "--summaries", "--config", cfg]) == 0
    assert "summaries: 1 files" in capsys.readouterr().out
    assert main(["summaries", str(repo), "--config", cfg]) == 0
    assert "app.py" in capsys.readouterr().out
