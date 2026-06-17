"""Result types for an indexing run."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ResolveStats(BaseModel):
    """Outcome of the pass-2 resolver."""

    imports_resolved: int = 0  # IMPORTS edges to in-repo files
    imports_external: int = 0  # IMPORTS edges to external (stdlib/third-party) packages
    refs_resolved: int = 0  # CALLS edges created (unique match)
    refs_unresolved: int = 0  # call sites with zero/ambiguous targets (recorded, not guessed)
    inherits_resolved: int = 0  # INHERITS edges created (base class -> in-repo class)


class RouteInfo(BaseModel):
    """One extracted endpoint (feat-011), for ``CodeGraph.routes`` / ``ckg
    routes`` / the ``ckg_routes`` tool."""

    method: str
    path: str
    framework: str
    handler: str  # handler symbol id (HANDLED_BY target)
    file: str
    line: int

    def to_dict(self) -> dict[str, object]:
        return self.model_dump()


class IndexReport(BaseModel):
    """Summary of a full ``IngestPipeline.run`` / ``CodeGraph.index``."""

    files_indexed: int = 0
    nodes: int = 0
    edges: int = 0
    by_node_kind: dict[str, int] = Field(default_factory=dict)
    by_edge_kind: dict[str, int] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    resolve: ResolveStats = Field(default_factory=ResolveStats)
    routes_extracted: int = 0  # feat-011: framework Route nodes emitted
    framework_unresolved: int = 0  # framework registrations seen but not extractable
    decisions_indexed: int = 0  # feat-010: ADR Decision nodes
    governs_resolved: int = 0  # GOVERNS edges from unambiguous ADR mentions
    mentions_unresolved: int = 0  # ADR mentions seen but not linked
