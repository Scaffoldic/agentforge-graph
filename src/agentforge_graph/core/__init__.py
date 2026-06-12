"""agentforge_graph.core — the locked schema and contracts.

The stable surface every other feature plugs into: typed node/edge
kinds, value types (with provenance + symbol-ID validation enforced at
construction), the symbol-ID grammar, and the ABCs. This package imports
nothing from ``agentforge`` (ADR-0001) — it is the deterministic engine
core and is usable standalone.
"""

from __future__ import annotations

from .contracts import Enricher, Extractor, GraphStore, VectorStore
from .kinds import EdgeKind, NodeKind
from .models import (
    Edge,
    Embedded,
    FileSubgraph,
    GraphQuery,
    Node,
    QueryResult,
    ScoredRef,
    SourceFile,
)
from .provenance import Provenance, Source
from .symbols import Descriptor, ParsedSymbol, SymbolID, normalize_path

__all__ = [
    # kinds
    "NodeKind",
    "EdgeKind",
    # provenance
    "Provenance",
    "Source",
    # symbols
    "SymbolID",
    "ParsedSymbol",
    "Descriptor",
    "normalize_path",
    # models
    "Node",
    "Edge",
    "FileSubgraph",
    "SourceFile",
    "GraphQuery",
    "QueryResult",
    "Embedded",
    "ScoredRef",
    # contracts
    "Extractor",
    "GraphStore",
    "VectorStore",
    "Enricher",
]
