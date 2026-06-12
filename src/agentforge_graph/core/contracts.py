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

from .kinds import EdgeKind
from .models import Edge, FileSubgraph, GraphQuery, Node, QueryResult, SourceFile


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
