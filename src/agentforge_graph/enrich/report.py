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
