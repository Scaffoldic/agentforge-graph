"""``PatternTagEnricher`` (feat-012) — orchestrate two-stage pattern tagging.

Stage-1 heuristics nominate; the injected ``PatternJudge`` confirms each under a
``budget_usd`` cap (the framework ``BudgetPolicy`` breaker — the first feature to
ride the AgentForge budget rails). Confirmed verdicts above the confidence floor
become ``PatternTag`` nodes + ``TAGGED`` edges with honest ``llm`` provenance.
Re-tag is idempotent (clear a judged symbol's old ``TAGGED`` first); a tripped
budget stops cleanly, leaving unjudged candidates for the next run. This is a
framework-layer module (ADR-0001: ``enrich`` may import ``agentforge``).
"""

from __future__ import annotations

from agentforge_core.production.budget import BudgetPolicy
from agentforge_core.production.exceptions import BudgetExceeded

from agentforge_graph.core import Edge, GraphStore, Node, NodeKind, Provenance
from agentforge_graph.core.kinds import EdgeKind

from .heuristics import PatternHeuristics
from .judge import PatternJudge
from .report import EnrichReport
from .taxonomy import is_pattern, pattern_tag_id


class PatternTagEnricher:
    version = "pattern-tags@1"  # bump on prompt/taxonomy change → re-tag

    def __init__(
        self,
        repo: str,
        judge: PatternJudge,
        *,
        heuristics: PatternHeuristics | None = None,
        confidence_floor: float = 0.7,
        budget_usd: float = 2.0,
        commit: str = "",
    ) -> None:
        self.repo = repo
        self.judge = judge
        self.heuristics = heuristics or PatternHeuristics()
        self.confidence_floor = confidence_floor
        self.budget_usd = budget_usd
        self.commit = commit
        self.last_judged_ids: list[str] = []

    async def enrich(self, store: GraphStore, symbol_ids: list[str]) -> EnrichReport:
        report = EnrichReport()
        candidates = await self.heuristics.nominate(store, symbol_ids)
        report.candidates = len(candidates)
        self.last_judged_ids = []
        if not candidates:
            return report

        budget = BudgetPolicy(usd=self.budget_usd, max_tokens=10**12, max_iterations=10**12)
        facts: list[Node | Edge] = []
        prev_cost = 0.0

        for cand in candidates:
            try:
                budget.check()
            except BudgetExceeded:
                report.budget_tripped = True
                break
            verdicts = await self.judge.judge(cand)
            report.judged += 1
            self.last_judged_ids.append(cand.symbol_id)
            prev_cost, delta = self.judge.cost_usd, self.judge.cost_usd - prev_cost
            budget.commit(delta)
            report.cost_usd = round(self.judge.cost_usd, 6)
            for v in verdicts:
                if not (
                    v.is_match and v.confidence >= self.confidence_floor and is_pattern(v.pattern)
                ):
                    continue
                prov = Provenance.llm(self.version, round(v.confidence, 4), self.commit)
                tag_id = pattern_tag_id(self.repo, v.pattern)
                facts.append(
                    Node(id=tag_id, kind=NodeKind.PATTERN_TAG, name=v.pattern, provenance=prov)
                )
                facts.append(
                    Edge(
                        src=cand.symbol_id,
                        dst=tag_id,
                        kind=EdgeKind.TAGGED,
                        attrs={"confidence": round(v.confidence, 4), "rationale": v.rationale},
                        provenance=prov,
                    )
                )
                report.tagged += 1
                report.by_pattern[v.pattern] = report.by_pattern.get(v.pattern, 0) + 1

        # idempotent re-tag: drop judged symbols' old tags, then write the new
        await store.clear_outgoing(self.last_judged_ids, EdgeKind.TAGGED)
        if facts:
            await store.add(facts)
        return report
