"""agentforge_graph.store — persistent storage adapters (feat-003).

Embedded-first (ADR-0006): the default ``Store`` writes a Kuzu graph DB
and a LanceDB vector index under ``.ckg/`` with no server. Server adapters
(Neo4j, FalkorDB) register out-of-tree via entry points. Imports nothing
from ``agentforge`` (ADR-0001).
"""

from __future__ import annotations

from .errors import (
    DriverNotFound,
    SchemaVersionError,
    StoreConfigError,
    StoreError,
)
from .kuzu_store import KuzuGraphStore
from .lance_store import LanceVectorStore

__all__ = [
    "KuzuGraphStore",
    "LanceVectorStore",
    "StoreError",
    "StoreConfigError",
    "DriverNotFound",
    "SchemaVersionError",
]
