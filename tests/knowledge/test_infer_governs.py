"""feat-010 follow-up: the optional ``infer_governs`` LLM pass proposes GOVERNS
edges for ADRs whose prose names no code, with honest ``llm`` provenance — while
NEVER touching decisions the deterministic parser already linked. Driven by the
``ScriptedMatcher`` so it is deterministic and credential-free."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.enrich import GovernsMatch, ScriptedMatcher
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent / "fixtures" / "repo"


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()


def _match_payment_service(title: str, text: str, candidates: object) -> list[GovernsMatch]:
    return [
        GovernsMatch(symbol_id=c.symbol_id, confidence=0.9, rationale="scripted")
        for c in candidates  # type: ignore[attr-defined]
        if c.name == "PaymentService"
    ]


async def _governs(cg: CodeGraph, decision_id: str) -> list[object]:
    return await cg.store.graph.adjacent(decision_id, [EdgeKind.GOVERNS], "out")


async def _decision(cg: CodeGraph, adr_num: str) -> str:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DECISION], limit=99))).nodes
    return next(n.id for n in nodes if adr_num in SymbolID.parse(n.id).path)


async def test_infers_governs_for_unlinked_decision(graph: CodeGraph) -> None:
    cg = graph
    # ADR-0007 is prose-only (no parsed GOVERNS); the matcher links it to PaymentService
    report = await cg.infer_governs(matcher=ScriptedMatcher(_match_payment_service))
    assert report.decisions_considered >= 1
    assert report.governs_inferred >= 1

    d7 = await _decision(cg, "0007")
    govs = await _governs(cg, d7)
    assert govs
    e = next(iter(govs))
    assert e.provenance.source == "llm"  # honest provenance
    assert SymbolID.parse(e.dst).descriptor == "PaymentService#"
    assert float(e.attrs.get("confidence", 0)) == pytest.approx(0.9)


async def test_parsed_decision_is_not_touched(graph: CodeGraph) -> None:
    cg = graph
    # ADR-0012 already has a PARSED GOVERNS (it names PaymentService) → skipped
    d12 = await _decision(cg, "0012")
    before = {(e.dst, e.provenance.source) for e in await _governs(cg, d12)}
    assert any(src == "parsed" for _, src in before)
    await cg.infer_governs(matcher=ScriptedMatcher(_match_payment_service))
    after = {(e.dst, e.provenance.source) for e in await _governs(cg, d12)}
    assert after == before  # untouched: no llm edges added, parsed link intact


async def test_below_floor_match_dropped(graph: CodeGraph) -> None:
    cg = graph
    low = ScriptedMatcher(
        lambda title, text, cands: [
            GovernsMatch(symbol_id=c.symbol_id, confidence=0.3, rationale="weak")
            for c in cands
            if c.name == "PaymentService"
        ]
    )
    report = await cg.infer_governs(matcher=low)
    assert report.governs_inferred == 0  # 0.3 < default floor 0.7


async def test_budget_trips_cleanly(tmp_path: Path) -> None:
    # two prose-only ADRs → the breaker trips before the 2nd (overrun bounded to 1)
    repo = tmp_path / "proj2"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "m.py").write_text("class Widget:\n    def go(self):\n        return 1\n")
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True)
    for n in ("0001", "0002"):
        (adr / f"{n}-x.md").write_text(
            f"# {n[-1]}. Rule {n}\n\nDate: 2025-01-01\n\n## Status\n\nAccepted\n\n"
            "## Decision\n\nAll writes must be idempotent and bounded.\n"
        )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        pricey = ScriptedMatcher(_match_payment_service, per_call_usd=5.0)
        report = await cg.infer_governs(matcher=pricey, budget_usd=0.01)
        assert report.decisions_considered == 2
        assert report.budget_tripped
    finally:
        await cg.close()


async def test_reinfer_is_idempotent(graph: CodeGraph) -> None:
    cg = graph
    m = ScriptedMatcher(_match_payment_service)
    r1 = await cg.infer_governs(matcher=m)
    d7 = await _decision(cg, "0007")
    after_first = len(await _governs(cg, d7))
    r2 = await cg.infer_governs(matcher=ScriptedMatcher(_match_payment_service))
    after_second = len(await _governs(cg, d7))
    assert after_first == after_second  # no duplicate edges on re-run
    assert r2.governs_inferred == r1.governs_inferred
