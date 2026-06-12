"""Result types for an indexing run."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResolveStats(BaseModel):
    """Outcome of the pass-2 resolver."""

    imports_resolved: int = 0  # IMPORTS edges to in-repo files
    imports_external: int = 0  # IMPORTS edges to external (stdlib/third-party) packages
    refs_resolved: int = 0  # CALLS edges created (unique match)
    refs_unresolved: int = 0  # call sites with zero/ambiguous targets (recorded, not guessed)


class IndexReport(BaseModel):
    """Summary of a full ``IngestPipeline.run`` / ``CodeGraph.index``."""

    files_indexed: int = 0
    nodes: int = 0
    edges: int = 0
    by_node_kind: dict[str, int] = Field(default_factory=dict)
    by_edge_kind: dict[str, int] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    resolve: ResolveStats = Field(default_factory=ResolveStats)
