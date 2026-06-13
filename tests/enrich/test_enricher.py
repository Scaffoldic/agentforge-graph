"""PatternTagEnricher with the deterministic ScriptedJudge (feat-012): tagging,
confidence floor, budget breaker, idempotent re-tag — no live model."""

from __future__ import annotations

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.enrich import PatternTagEnricher, ScriptedJudge, Verdict
from agentforge_graph.enrich.heuristics import Candidate, class_and_function_ids
from agentforge_graph.ingest import CodeGraph


async def _ids(cg: CodeGraph) -> list[str]:
    nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
    return class_and_function_ids(nodes)


async def _tag_count(cg: CodeGraph) -> int:
    nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
    total = 0
    for n in nodes:
        total += len(await cg.store.graph.adjacent(n.id, [EdgeKind.TAGGED], "out"))
    return total


async def test_confirm_all_tags_every_candidate(graph: CodeGraph) -> None:
    enricher = PatternTagEnricher("proj", ScriptedJudge())
    report = await enricher.enrich(graph.store.graph, await _ids(graph))
    assert report.candidates == report.judged >= 5
    assert report.tagged == report.candidates  # confirm-all, all above floor
    assert report.by_pattern.get("Repository") == 1


async def test_confidence_floor_drops_low(graph: CodeGraph) -> None:
    def low(c: Candidate) -> list[Verdict]:
        return [
            Verdict(pattern=p, is_match=True, confidence=0.4, rationale="x") for p in c.patterns
        ]

    enricher = PatternTagEnricher("proj", ScriptedJudge(low), confidence_floor=0.7)
    report = await enricher.enrich(graph.store.graph, await _ids(graph))
    assert report.judged >= 5
    assert report.tagged == 0  # all below the floor
    assert await _tag_count(graph) == 0


async def test_rejected_verdict_not_tagged(graph: CodeGraph) -> None:
    def reject(c: Candidate) -> list[Verdict]:
        return [
            Verdict(pattern=p, is_match=False, confidence=0.9, rationale="no") for p in c.patterns
        ]

    report = await PatternTagEnricher("proj", ScriptedJudge(reject)).enrich(
        graph.store.graph, await _ids(graph)
    )
    assert report.tagged == 0


async def test_budget_breaker_trips_and_persists_partial(graph: CodeGraph) -> None:
    judge = ScriptedJudge(per_call_usd=1.0)
    # concurrency=1 → the strict per-call breaker (ENH-002 accounts per batch)
    enricher = PatternTagEnricher("proj", judge, budget_usd=1.5, concurrency=1)
    report = await enricher.enrich(graph.store.graph, await _ids(graph))
    assert report.budget_tripped is True
    assert report.judged == 2  # check passes at spent 0 and 1.0; trips at 2.0 >= 1.5
    assert report.tagged == 2  # partial progress persisted
    assert len(enricher.last_judged_ids) == 2


async def test_re_enrich_is_idempotent(graph: CodeGraph) -> None:
    ids = await _ids(graph)
    await PatternTagEnricher("proj", ScriptedJudge()).enrich(graph.store.graph, ids)
    first = await _tag_count(graph)
    await PatternTagEnricher("proj", ScriptedJudge()).enrich(graph.store.graph, ids)
    assert await _tag_count(graph) == first  # cleared then re-added, no duplicates


async def test_concurrency_is_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # ENH-002: concurrent batches produce the same tags as sequential. Two fresh
    # indexes (same code, same leaf dir name → same repo slug) so the only
    # variable is concurrency; first-run enrich avoids any re-tag.
    from .conftest import PATTERNS_CODE

    async def tags_at(concurrency: int, parent: str) -> set[tuple[str, str]]:
        repo = tmp_path / parent / "proj"
        repo.mkdir(parents=True)
        (repo / "app.py").write_text(PATTERNS_CODE)
        cg = await CodeGraph.index(repo_path=repo)
        try:
            ids = await _ids(cg)
            await PatternTagEnricher("proj", ScriptedJudge(), concurrency=concurrency).enrich(
                cg.store.graph, ids
            )
            nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
            out: set[tuple[str, str]] = set()
            for n in nodes:
                for e in await cg.store.graph.adjacent(n.id, [EdgeKind.TAGGED], "out"):
                    tag = await cg.store.graph.get(e.dst)
                    if tag is not None:
                        out.add((SymbolID.parse(e.src).descriptor, tag.name))
            return out
        finally:
            await cg.close()

    assert await tags_at(1, "a") == await tags_at(4, "b")


async def test_pattern_tag_nodes_have_llm_provenance(graph: CodeGraph) -> None:
    from agentforge_graph.core import Source

    await PatternTagEnricher("proj", ScriptedJudge()).enrich(graph.store.graph, await _ids(graph))
    tags = (await graph.store.graph.query(GraphQuery(kinds=[NodeKind.PATTERN_TAG], limit=99))).nodes
    assert tags and all(t.provenance.source is Source.LLM for t in tags)
