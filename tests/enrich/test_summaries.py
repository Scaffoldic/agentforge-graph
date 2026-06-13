"""Bottom-up summaries (feat-012) with ScriptedSummarizer + FakeEmbedder — no
model. SummaryEnricher behavior, embedding/search, idempotency, budget."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.embed import FakeEmbedder
from agentforge_graph.enrich import ScriptedSummarizer, SummaryEnricher, summary_id
from agentforge_graph.ingest import CodeGraph

CODE_A = (
    "from b import helper\n\n\n"
    "class OrderService:\n    def place(self, o):\n        return helper(o)\n"
)
CODE_B = "def helper(x):\n    return x\n"


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "a.py").write_text(CODE_A)
    (repo / "b.py").write_text(CODE_B)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


async def _file_ids(cg: CodeGraph) -> list[str]:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.FILE], limit=99))).nodes
    return [n.id for n in nodes]


def _enricher(repo: str = "proj") -> SummaryEnricher:
    return SummaryEnricher(repo, ScriptedSummarizer(), embedder=FakeEmbedder(dim=8))


async def test_bottom_up_file_and_repo(graph: CodeGraph) -> None:
    report = await _enricher().enrich(graph.store, await _file_ids(graph))
    assert report.files_summarized == 2
    assert report.repo_summarized is True
    summaries = (
        await graph.store.graph.query(GraphQuery(kinds=[NodeKind.SUMMARY], limit=99))
    ).nodes
    levels = sorted(str(n.attrs["level"]) for n in summaries)
    assert levels == ["file", "file", "repo"]


async def test_summarizes_edges_point_to_targets(graph: CodeGraph) -> None:
    await _enricher().enrich(graph.store, await _file_ids(graph))
    sid = summary_id("proj", "a.py")
    edges = await graph.store.graph.adjacent(sid, [EdgeKind.SUMMARIZES], "out")
    assert len(edges) == 1
    assert SymbolID.parse(edges[0].dst).path == "a.py"  # → the file node


async def test_summaries_are_embedded_and_searchable(graph: CodeGraph) -> None:
    await _enricher().enrich(graph.store, await _file_ids(graph))
    emb = FakeEmbedder(dim=8)
    # the exact summary text embeds to the stored vector → search finds it
    text = "summary of a.py (1 symbols)"
    qvec = (await emb.embed([text], "query"))[0]
    hits = await graph.store.vectors.search(qvec, k=5, filter={"kind": NodeKind.SUMMARY.value})
    assert summary_id("proj", "a.py") in {h.ref for h in hits}


async def test_re_summarize_is_idempotent(graph: CodeGraph) -> None:
    ids = await _file_ids(graph)
    await _enricher().enrich(graph.store, ids)
    await _enricher().enrich(graph.store, ids)
    summaries = (
        await graph.store.graph.query(GraphQuery(kinds=[NodeKind.SUMMARY], limit=99))
    ).nodes
    assert len(summaries) == 3  # 2 files + 1 repo, no duplicates
    edges = await graph.store.graph.adjacent(
        summary_id("proj", "a.py"), [EdgeKind.SUMMARIZES], "out"
    )
    assert len(edges) == 1  # SUMMARIZES not duplicated


async def test_budget_trips_before_repo(graph: CodeGraph) -> None:
    class CostlySummarizer(ScriptedSummarizer):
        def __init__(self) -> None:
            super().__init__()
            self._c = 0.0

        async def summarize_file(self, ctx, max_words):  # type: ignore[no-untyped-def]
            self._c += 1.0
            return await super().summarize_file(ctx, max_words)

        @property
        def cost_usd(self) -> float:
            return self._c

    enricher = SummaryEnricher(
        "proj", CostlySummarizer(), embedder=FakeEmbedder(dim=8), budget_usd=1.5
    )
    report = await enricher.enrich(graph.store, await _file_ids(graph))
    assert report.budget_tripped is True
    assert report.files_summarized == 2  # check passes at 0 and 1.0; trips at 2.0 >= 1.5
    assert report.repo_summarized is False  # budget tripped before the repo tier


async def test_levels_file_only_skips_repo(graph: CodeGraph) -> None:
    enricher = SummaryEnricher(
        "proj", ScriptedSummarizer(), embedder=FakeEmbedder(dim=8), levels=["file"]
    )
    report = await enricher.enrich(graph.store, await _file_ids(graph))
    assert report.files_summarized == 2 and report.repo_summarized is False
