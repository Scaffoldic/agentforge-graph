"""Value types for the graph: nodes, edges, the per-file subgraph, and
the minimal query/result shapes.

``Node``/``Edge`` validate their IDs and (via ``Provenance``) their
attribution at construction, so the graph cannot hold a malformed or
unattributed fact. ``FileSubgraph`` is the unit of ingestion *and*
deletion — keyed by ``(path, content_hash)`` — which is what makes
incremental indexing (feat-004) a thin layer. See ADR-0003/0004.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .kinds import EdgeKind, NodeKind
from .provenance import Provenance, Source
from .symbols import SymbolID


def _require_symbol_id(value: str) -> str:
    SymbolID.parse(value)  # raises ValueError if malformed
    return value


class SourceFile(BaseModel):
    """A single file handed to an ``Extractor``."""

    model_config = ConfigDict(frozen=True)

    path: str  # repo-relative, posix
    text: str
    language: str
    content_hash: str  # sha256 of the file bytes


class Node(BaseModel):
    """A typed entity in the graph."""

    id: str  # a SymbolID string
    kind: NodeKind
    name: str
    span: tuple[int, int] | None = None  # (start_line, end_line), 1-based
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

    @field_validator("id")
    @classmethod
    def _check_id(cls, v: str) -> str:
        return _require_symbol_id(v)


class Edge(BaseModel):
    """A typed relationship between two symbols."""

    src: str
    dst: str
    kind: EdgeKind
    attrs: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance

    @field_validator("src", "dst")
    @classmethod
    def _check_endpoint(cls, v: str) -> str:
        return _require_symbol_id(v)


class FileSubgraph(BaseModel):
    """Everything extracted from one file — the ingestion/deletion unit."""

    path: str  # repo-relative, posix
    content_hash: str
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)


class GraphQuery(BaseModel):
    """A minimal, flat node filter (0.1). Graph traversal lives in
    ``GraphStore.neighbors``, not here. Extends by minor bump."""

    kinds: list[NodeKind] | None = None
    name: str | None = None  # exact match
    path_prefix: str | None = None
    edge_kind: EdgeKind | None = None
    min_source: Source | None = None  # provenance floor
    limit: int = 100

    @field_validator("limit")
    @classmethod
    def _positive_limit(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("limit must be > 0")
        return v


class QueryResult(BaseModel):
    """The result of a ``GraphStore.query``."""

    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    truncated: bool = False  # True if `limit` clipped the result
