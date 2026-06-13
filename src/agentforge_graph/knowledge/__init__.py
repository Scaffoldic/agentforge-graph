"""ADR & docs ingestion (feat-010): connect architecture decisions to the code
they govern — the gap no surveyed tool fills (research §3.3).

MVP: ADR markdown → ``Decision`` nodes (+ body ``DocChunk``s) with **parsed**
``GOVERNS``/``SUPERSEDES`` edges, ingested as per-ADR ``FileSubgraph`` upserts
(so they ride feat-004 incrementality). Retrieval surfaces a governing decision
when its governed code is retrieved. Zero ``agentforge`` imports (ADR-0001).
"""

from __future__ import annotations

from .adr import ADRParser, ParsedADR
from .ingest import KnowledgeIngestor
from .mentions import Mentions, extract_mentions, resolve_mentions
from .report import DecisionInfo, KnowledgeStats

__all__ = [
    "ADRParser",
    "ParsedADR",
    "KnowledgeIngestor",
    "Mentions",
    "extract_mentions",
    "resolve_mentions",
    "DecisionInfo",
    "KnowledgeStats",
]
