"""``DecisionGovernsInferencer`` (feat-010 follow-up) — the optional LLM pass that
proposes ``GOVERNS`` edges for ADRs whose prose names no code.

Only decisions with **zero parsed** ``GOVERNS`` edges are considered (the LLM
fills the gap the deterministic parser left; it never overrides parsed links).
Each considered decision's prose is matched against the repo's candidate symbols
under a ``budget_usd`` cap (the framework ``BudgetPolicy``); matches above the
confidence floor become ``GOVERNS`` edges with honest ``llm`` provenance. Re-run
is idempotent — a considered decision's prior ``llm`` GOVERNS are cleared first
(safe: it has no parsed GOVERNS to clobber). Off by default; ``ckg enrich
--decisions`` runs it. Framework-layer (ADR-0001: ``enrich`` may import
``agentforge``).
"""

from __future__ import annotations

from agentforge_core.production.budget import BudgetPolicy
from agentforge_core.production.exceptions import BudgetExceeded

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
)

from .governs import GovernsCandidate, GovernsMatcher
from .report import GovernsReport

_ALL = 10_000_000
_CANDIDATE_KINDS = {NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD}


class DecisionGovernsInferencer:
    version = "infer-governs@1"  # bump on prompt change → re-infer

    def __init__(
        self,
        repo: str,
        matcher: GovernsMatcher,
        *,
        confidence_floor: float = 0.7,
        budget_usd: float = 1.0,
        max_candidates: int = 60,
        commit: str = "",
    ) -> None:
        self.repo = repo
        self.matcher = matcher
        self.confidence_floor = confidence_floor
        self.budget_usd = budget_usd
        self.max_candidates = max(1, max_candidates)
        self.commit = commit

    async def enrich(self, store: GraphStore) -> GovernsReport:
        report = GovernsReport()
        nodes = (await store.query(GraphQuery(limit=_ALL))).nodes
        decisions = [n for n in nodes if n.kind is NodeKind.DECISION]
        report.decisions_total = len(decisions)
        if not decisions:
            return report

        candidates = self._candidates(nodes)
        report.candidates = len(candidates)
        if not candidates:
            return report

        # only decisions the deterministic parser left ungoverned (no parsed link)
        targets: list[Node] = []
        for d in decisions:
            govs = await store.adjacent(d.id, [EdgeKind.GOVERNS], "out")
            if not any(e.provenance.source == "parsed" for e in govs):
                targets.append(d)
        report.decisions_considered = len(targets)
        if not targets:
            return report

        budget = BudgetPolicy(usd=self.budget_usd, max_tokens=10**12, max_iterations=10**12)
        facts: list[Node | Edge] = []
        inferred_ids: list[str] = []
        for d in targets:
            try:
                budget.check()
            except BudgetExceeded:
                report.budget_tripped = True
                break
            text = await self._decision_text(store, d.id)
            before = self.matcher.cost_usd
            matches = await self.matcher.match(d.attrs.get("title", d.name), text, candidates)
            budget.commit(self.matcher.cost_usd - before)
            report.cost_usd = round(self.matcher.cost_usd, 6)
            inferred_ids.append(d.id)
            for m in matches:
                if m.confidence < self.confidence_floor:
                    continue
                prov = Provenance.llm(self.version, round(m.confidence, 4), self.commit)
                facts.append(
                    Edge(
                        src=d.id,
                        dst=m.symbol_id,
                        kind=EdgeKind.GOVERNS,
                        attrs={"confidence": round(m.confidence, 4), "rationale": m.rationale},
                        provenance=prov,
                    )
                )
                report.governs_inferred += 1

        # idempotent re-infer: drop considered decisions' prior llm GOVERNS, then
        # write the new ones. Safe because a considered decision has no *parsed*
        # GOVERNS, so this never removes a deterministic link.
        if inferred_ids:
            await store.clear_outgoing(inferred_ids, EdgeKind.GOVERNS)
        if facts:
            await store.add(facts)
        return report

    def _candidates(self, nodes: list[Node]) -> list[GovernsCandidate]:
        """Deterministic, bounded candidate set: in-repo Class/Function/Method
        symbols sorted by id, capped. (Repo-map-ranked candidates are a refinement.)"""
        out: list[GovernsCandidate] = []
        for n in sorted(nodes, key=lambda z: z.id):
            if n.kind not in _CANDIDATE_KINDS:
                continue
            from agentforge_graph.core import SymbolID

            ps = SymbolID.parse(n.id)
            out.append(
                GovernsCandidate(
                    symbol_id=n.id,
                    name=n.name,
                    kind=n.kind.value,
                    signature=str(n.attrs.get("signature", "")),
                    path=ps.path,
                )
            )
            if len(out) >= self.max_candidates:
                break
        return out

    @staticmethod
    async def _decision_text(store: GraphStore, decision_id: str) -> str:
        """The decision's prose — its DocChunk bodies, in order, bounded."""
        chunks = [
            n
            for n in await store.neighbors(decision_id, [EdgeKind.CONTAINS], depth=1)
            if n.kind is NodeKind.DOC_CHUNK
        ]
        chunks.sort(key=lambda n: int(n.attrs.get("seq", 0)))
        parts = [f"{n.attrs.get('heading', '')}\n{n.attrs.get('text', '')}".strip() for n in chunks]
        return "\n\n".join(p for p in parts if p)[:6000]
