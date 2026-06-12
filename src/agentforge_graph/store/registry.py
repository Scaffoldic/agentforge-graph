"""Driver registry: config driver-name → adapter class.

Built-in embedded drivers are registered here; opt-in server adapters
(Neo4j, FalkorDB, pgvector) register out-of-tree via entry-point groups, so
they install as ``pip install`` + one config line with no core change.
"""

from __future__ import annotations

from importlib.metadata import entry_points
from typing import Any

from .errors import DriverNotFound
from .kuzu_store import KuzuGraphStore
from .lance_store import LanceVectorStore

GRAPH_GROUP = "agentforge_graph.graph_drivers"
VECTOR_GROUP = "agentforge_graph.vector_drivers"

_GRAPH_BUILTINS: dict[str, Any] = {"kuzu": KuzuGraphStore}
_VECTOR_BUILTINS: dict[str, Any] = {"lancedb": LanceVectorStore}


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
