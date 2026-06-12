"""The locked ABCs every later feature plugs into.

- ``Extractor`` — turns a file into a ``FileSubgraph`` (feat-002, feat-011).
- ``GraphStore`` — persists subgraphs and enrichment facts, answers
  queries and neighborhood walks (feat-003 adapters).
- ``Enricher`` — derives new nodes/edges from the existing graph
  (feat-010/012).

Signatures only; implementations ship with their owning features. The
constructor/method surface here is the stable contract — additions are
minor bumps, removals/renames are major. See ADR-0001 (layering: this
module imports nothing from ``agentforge``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Literal

from .kinds import EdgeKind
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

# Direction of a 1-hop edge walk: out = node is src, in = node is dst.
Direction = Literal["out", "in", "both"]


class Extractor(ABC):
    """Produces a ``FileSubgraph`` from a single file, in isolation.

    Extraction must not read other files (per-file isolation is what
    makes feat-004 incremental); cross-file edges are emitted as
    candidate references and resolved in a later pass.
    """

    name: str

    @abstractmethod
    def extract(self, file: SourceFile) -> FileSubgraph: ...


class GraphStore(ABC):
    """Persistence + query contract. feat-003 ships the adapters."""

    @abstractmethod
    async def upsert(self, subgraph: FileSubgraph) -> None:
        """Insert/replace all nodes & edges for ``subgraph.path``
        transactionally (delete prior content for that path, add new)."""

    @abstractmethod
    async def add(self, items: list[Node | Edge]) -> None:
        """Persist facts not tied to a single file (enrichment, resolved
        cross-file edges). These survive ``delete_file`` of code files."""

    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """Remove everything previously upserted for ``path``."""

    @abstractmethod
    async def query(self, q: GraphQuery) -> QueryResult:
        """Exact-match node lookup with the flat ``GraphQuery`` filter."""

    @abstractmethod
    async def neighbors(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        depth: int = 1,
    ) -> list[Node]:
        """Nodes reachable from ``node_id`` over edges of ``kinds`` within
        ``depth`` hops (either direction)."""

    @abstractmethod
    async def get(self, node_id: str) -> Node | None:
        """Fetch a node by id, or ``None``."""

    @abstractmethod
    async def adjacent(
        self,
        node_id: str,
        kinds: list[EdgeKind] | None = None,
        direction: Direction = "both",
    ) -> list[Edge]:
        """The 1-hop edges touching ``node_id`` (``out``: it is the src;
        ``in``: it is the dst; ``both``), optionally filtered by edge kind.
        Returns full ``Edge`` objects, so the caller sees each edge's kind,
        direction and provenance (feat-006 retrieval scoring)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources. Safe to call more than once."""


class VectorStore(ABC):
    """Vector persistence + similarity search. feat-003 ships the LanceDB
    adapter; feat-005 produces the ``Embedded`` items it stores. A peer of
    ``GraphStore`` — the ``Store`` facade (feat-003) owns one of each and
    joins them (vector hit -> graph expansion) for retrieval (feat-006)."""

    @abstractmethod
    async def upsert(self, items: list[Embedded]) -> None:
        """Insert/replace vectors keyed by ``Embedded.ref``."""

    @abstractmethod
    async def search(
        self,
        vector: list[float],
        k: int,
        filter: dict[str, Any] | None = None,
    ) -> list[ScoredRef]:
        """Top-``k`` nearest refs, optionally constrained by an attribute
        ``filter`` (e.g. ``{"kind": "Chunk"}``)."""

    @abstractmethod
    async def delete_where(self, filter: dict[str, Any]) -> None:
        """Drop vectors matching ``filter`` (feat-004 invalidation)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources. Safe to call more than once."""


class Enricher(ABC):
    """Derives new nodes/edges from the existing graph (feat-010/012).

    Returns the facts it derived; the caller persists them via
    ``GraphStore.add``. Derived facts must carry ``source=llm``
    provenance with a confidence (ADR-0004)."""

    name: str

    @abstractmethod
    async def enrich(self, store: GraphStore) -> list[Node | Edge]: ...
