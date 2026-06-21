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
from .facade import Store
from .kuzu_store import KuzuGraphStore
from .lance_store import LanceVectorStore
from .location import is_read_only, repo_key, resolve_root
from .registry import graph_driver, vector_driver

__all__ = [
    "Store",
    "KuzuGraphStore",
    "LanceVectorStore",
    "graph_driver",
    "vector_driver",
    "is_read_only",
    "repo_key",
    "resolve_root",
    "StoreError",
    "StoreConfigError",
    "DriverNotFound",
    "SchemaVersionError",
]
