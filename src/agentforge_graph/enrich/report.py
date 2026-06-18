"""Result types for LLM enrichment (feat-012)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EnrichReport(BaseModel):
    """Outcome of one ``PatternTagEnricher.enrich`` run."""

    candidates: int = 0  # symbols the heuristics nominated
    judged: int = 0  # candidates sent to the judge
    tagged: int = 0  # TAGGED edges written (confirmed, above floor)
    cost_usd: float = 0.0
    budget_tripped: bool = False
    by_pattern: dict[str, int] = Field(default_factory=dict)


class TaggedInfo(BaseModel):
    """One symbol's pattern tag, for ``CodeGraph.tagged`` / ``ckg_explain``."""

    symbol_id: str
    pattern: str
    confidence: float
    rationale: str

    def to_dict(self) -> dict[str, object]:
        return self.model_dump()


class SummaryReport(BaseModel):
    """Outcome of one ``SummaryEnricher.enrich`` run."""

    files_summarized: int = 0
    repo_summarized: bool = False
    cost_usd: float = 0.0
    budget_tripped: bool = False


class GovernsReport(BaseModel):
    """Outcome of one ``DecisionGovernsInferencer.enrich`` run (feat-010)."""

    decisions_total: int = 0  # Decision nodes in the graph
    decisions_considered: int = 0  # those with zero *parsed* GOVERNS (the LLM gap)
    candidates: int = 0  # symbols offered to the matcher
    governs_inferred: int = 0  # llm GOVERNS edges written (above the floor)
    cost_usd: float = 0.0
    budget_tripped: bool = False


class SummaryInfo(BaseModel):
    """One summary, for ``CodeGraph.summaries`` / ``ckg_explain``."""

    target: str  # the symbol/file/repo node id it summarizes
    level: str
    text: str
    path: str

    def to_dict(self) -> dict[str, object]:
        return self.model_dump()
