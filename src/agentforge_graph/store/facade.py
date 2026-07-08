"""The ``Store`` facade — one ``GraphStore`` + one ``VectorStore`` resolved
from ``ckg.yaml``, plus the vector→graph join (``expand``) that retrieval
(feat-006) builds on. Embedded-first: the default writes ``.ckg/graph.kuzu``
and ``.ckg/vectors.lance`` under the repo root (ADR-0006).

All failure modes (unknown driver, schema mismatch, malformed config) raise
at ``open`` — never mid-index.
"""

from __future__ import annotations

import json
from pathlib import Path

from agentforge_graph.config import ConfigSource, StoreConfig
from agentforge_graph.core import EdgeKind, GraphStore, Node, QueryResult, ScoredRef, VectorStore

from .errors import SchemaVersionError, StoreError
from .location import is_read_only, resolve_root
from .query import (
    QueryCapable,
    QueryDisabled,
    QuerySettings,
    ResultTable,
    parse_query,
    validate_query,
)
from .registry import graph_driver, vector_driver

# Store-level on-disk layout version. Bumped when the .ckg/ layout changes;
# 0.x policy on mismatch is rebuild (the index is derivable — ADR-0006).
STORE_SCHEMA_VERSION = 1


class Store:
    """Owns a graph store and a vector store, resolved from config."""

    def __init__(self, graph: GraphStore, vectors: VectorStore, config: StoreConfig) -> None:
        self.graph = graph
        self.vectors = vectors
        self.config = config

    @classmethod
    async def open(cls, repo_path: str | Path = ".", config: ConfigSource = None) -> Store:
        """Resolve drivers from ``config`` (an ``agentforge.yaml``/``ckg.yaml``
        path, or discovered in ``repo_path``) and open the embedded index under
        ``repo_path``/<store.path>. Raises before any store is opened if the
        config or on-disk schema is bad."""
        from agentforge_graph.config import resolve_config

        config = resolve_config(config, repo_path)
        cfg = StoreConfig.load(config)
        root = resolve_root(repo_path, cfg)  # ENH-018: in-repo .ckg or central subdir
        # ENH-018: a read-only consumer never creates an index — it errors on a
        # missing one and only schema-checks an existing one.
        _check_or_init_meta(root, read_only=is_read_only(cfg))
        graph_cls = graph_driver(cfg.graph.driver)
        vector_cls = vector_driver(cfg.vectors.driver)
        # Embedded drivers use the path under .ckg/; server drivers (ENH-004)
        # ignore the path and read connection details from their config block.
        graph: GraphStore = await graph_cls.open(root / "graph.kuzu", config=cfg.graph.config)
        vectors: VectorStore = await vector_cls.open(
            root / "vectors.lance", config=cfg.vectors.config
        )
        return cls(graph, vectors, cfg)

    async def expand(
        self,
        refs: list[ScoredRef],
        kinds: list[EdgeKind] | None = None,
        depth: int = 1,
    ) -> QueryResult:
        """Join vector hits back into the graph: for each ref, collect the
        node and its ``kinds``-edge neighborhood within ``depth`` hops. The
        single place the graph+vector join lives (feat-006)."""
        nodes: dict[str, Node] = {}
        for r in refs:
            hit = await self.graph.get(r.ref)
            if hit is not None:
                nodes[hit.id] = hit
            for nb in await self.graph.neighbors(r.ref, kinds, depth):
                nodes[nb.id] = nb
        return QueryResult(nodes=list(nodes.values()))

    @property
    def query_enabled(self) -> bool:
        """True if the active graph backend can execute structural queries."""
        return isinstance(self.graph, QueryCapable)

    @property
    def query_capabilities(self) -> frozenset[str]:
        """The capability tiers the active backend executes (empty if none)."""
        graph = self.graph
        return graph.capabilities if isinstance(graph, QueryCapable) else frozenset()

    async def query_graph(self, text: str, settings: QuerySettings) -> ResultTable:
        """Parse, validate (against this backend's capabilities), and execute a
        read-only structural query. Raises ``QueryError`` on bad input or
        ``QueryDisabled`` if the backend is not query-capable."""
        graph = self.graph
        if not isinstance(graph, QueryCapable):
            raise QueryDisabled(type(graph).__name__)
        ast = parse_query(text)
        validate_query(ast, graph.capabilities)
        return await graph.run_query(ast, settings)

    async def close(self) -> None:
        await self.graph.close()
        await self.vectors.close()


def _check_or_init_meta(root: Path, read_only: bool = False) -> None:
    meta = root / "meta.json"
    if meta.exists():
        data = json.loads(meta.read_text())
        on_disk = data.get("schema_version")
        if on_disk != STORE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"index at {root} is schema v{on_disk}, this build expects "
                f"v{STORE_SCHEMA_VERSION}; rebuild the index (0.x policy)"
            )
        return
    if read_only:
        raise StoreError(
            f"no index at {root} — the store is read-only (nothing to read). "
            "Build the index where it is writable, then point consumers here."
        )
    root.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps({"schema_version": STORE_SCHEMA_VERSION, "indexed_commit": ""}, indent=2)
    )
