"""Result types for ADR/knowledge ingestion (feat-010)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class KnowledgeStats(BaseModel):
    """Outcome of one ``KnowledgeIngestor.ingest`` run."""

    decisions_indexed: int = 0
    governs_resolved: int = 0  # GOVERNS edges created from unambiguous mentions
    mentions_unresolved: int = 0  # mentions seen but not linked (unknown/ambiguous)
    docs_indexed: int = 0  # general doc files ingested (doc_globs, feat-010)
    describes_resolved: int = 0  # DESCRIBES edges created from doc mentions


class DecisionInfo(BaseModel):
    """One decision, for ``CodeGraph.decisions`` / ``ckg decisions`` / the
    ``ckg_decisions`` tool."""

    id: str
    adr_id: str
    title: str
    status: str
    date: str
    path: str
    governs: list[str] = Field(default_factory=list)  # node ids this decision governs

    def to_dict(self) -> dict[str, object]:
        return self.model_dump()
