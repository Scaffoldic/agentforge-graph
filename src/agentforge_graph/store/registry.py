"""Driver registry: config driver-name → adapter class.

Embedded drivers (Kuzu, LanceDB) ship by default; first-party **server** drivers
(Neo4j graph, pgvector — ENH-004) are registered too but their DB SDK is imported
lazily inside the adapter's ``open``, so they cost nothing until selected and
need only their extra installed (``pip install agentforge-graph[neo4j|pgvector]``).
Third-party adapters still register out-of-tree via the entry-point groups.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .errors import DriverNotFound
from .kuzu_store import KuzuGraphStore
from .lance_store import LanceVectorStore
from .neo4j_store import Neo4jGraphStore
from .pgvector_store import PgVectorStore

GRAPH_GROUP = "agentforge_graph.graph_drivers"
VECTOR_GROUP = "agentforge_graph.vector_drivers"

_GRAPH_BUILTINS: dict[str, Any] = {"kuzu": KuzuGraphStore, "neo4j": Neo4jGraphStore}
_VECTOR_BUILTINS: dict[str, Any] = {"lancedb": LanceVectorStore, "pgvector": PgVectorStore}


def _resolve(name: str, builtins: dict[str, Any], group: str) -> Any:
    if name in builtins:
        return builtins[name]
    for ep in entry_points(group=group):
        if ep.name == name:
            return ep.load()
    known = sorted(builtins)
    raise DriverNotFound(f"unknown driver {name!r}; built-in drivers: {known}")


def graph_driver(name: str) -> Any:
    """The graph-store class for a config ``driver`` name."""
    return _resolve(name, _GRAPH_BUILTINS, GRAPH_GROUP)


def vector_driver(name: str) -> Any:
    """The vector-store class for a config ``driver`` name."""
    return _resolve(name, _VECTOR_BUILTINS, VECTOR_GROUP)
