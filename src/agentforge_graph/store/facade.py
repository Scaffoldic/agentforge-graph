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

from agentforge_graph.config import StoreConfig
from agentforge_graph.core import EdgeKind, GraphStore, Node, QueryResult, ScoredRef, VectorStore

from .errors import SchemaVersionError
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
    async def open(cls, repo_path: str | Path = ".", config: str | Path | None = None) -> Store:
        """Resolve drivers from ``config`` (a ckg.yaml path) and open the
        embedded index under ``repo_path``/<store.path>. Raises before any
        store is opened if the config or on-disk schema is bad."""
        cfg = StoreConfig.load(config)
        root = Path(repo_path) / cfg.path
        _check_or_init_meta(root)  # fail-at-startup on schema mismatch
        graph_cls = graph_driver(cfg.graph.driver)
        vector_cls = vector_driver(cfg.vectors.driver)
        graph: GraphStore = await graph_cls.open(root / "graph.kuzu")
        vectors: VectorStore = await vector_cls.open(root / "vectors.lance")
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

    async def close(self) -> None:
        await self.graph.close()
        await self.vectors.close()


def _check_or_init_meta(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    meta = root / "meta.json"
    if meta.exists():
        data = json.loads(meta.read_text())
        on_disk = data.get("schema_version")
        if on_disk != STORE_SCHEMA_VERSION:
            raise SchemaVersionError(
                f"index at {root} is schema v{on_disk}, this build expects "
                f"v{STORE_SCHEMA_VERSION}; rebuild the index (0.x policy)"
            )
    else:
        meta.write_text(
            json.dumps({"schema_version": STORE_SCHEMA_VERSION, "indexed_commit": ""}, indent=2)
        )
