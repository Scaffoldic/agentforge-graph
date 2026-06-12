"""``EmbedPipeline`` — chunk the indexed code and embed the chunks.

Per file: pull its symbol nodes from the graph, chunk them, write `CHUNK`
nodes + `CHUNK_OF` edges, embed the chunk texts, and upsert vectors. Coarse
incrementality at 0.1: if a file's chunk-hash set is unchanged, skip
re-embedding (saves cost); otherwise clean-replace the file's chunk vectors.
feat-004 will scope this to a DirtySet.
"""

from __future__ import annotations

from agentforge_graph.chunking import Chunker
from agentforge_graph.core import (
    Edge,
    EdgeKind,
    Embedded,
    GraphQuery,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)
from agentforge_graph.ingest import PackRegistry, RepoSource
from agentforge_graph.store import Store

from .base import Embedder
from .report import EmbedReport

_ALL = 10_000_000


class EmbedPipeline:
    def __init__(self, chunker: Chunker, embedder: Embedder, commit: str = "") -> None:
        self.chunker = chunker
        self.embedder = embedder
        self.commit = commit
        self.name = "cast-chunker"

    async def run(self, store: Store, source: RepoSource, registry: PackRegistry) -> EmbedReport:
        report = EmbedReport(model=self.embedder.name, dim=self.embedder.dim)
        prov = Provenance.parsed(self.name, self.commit)

        for sf in source.iter_files(registry):
            nodes_for_path = [
                n
                for n in (
                    await store.graph.query(GraphQuery(path_prefix=sf.path, limit=_ALL))
                ).nodes
                if SymbolID.parse(n.id).path == sf.path
            ]
            symbols = [n for n in nodes_for_path if n.kind is not NodeKind.CHUNK]
            if not symbols:
                continue
            chunks = self.chunker.chunk(sf, symbols)
            if not chunks:
                continue
            report.files += 1
            report.chunks += len(chunks)

            prior = {
                n.attrs.get("content_hash") for n in nodes_for_path if n.kind is NodeKind.CHUNK
            }
            if prior and prior == {c.content_hash for c in chunks}:
                report.skipped_unchanged += 1
                continue

            repo = SymbolID.parse(symbols[0].id).repo
            file_id = SymbolID.for_symbol(sf.language, repo, sf.path, "")
            graph_items: list[Node | Edge] = []
            for ch in chunks:
                graph_items.append(
                    Node(
                        id=ch.id,
                        kind=NodeKind.CHUNK,
                        name=f"chunk{ch.seq}",
                        span=ch.span,
                        attrs={
                            "path": ch.path,
                            "token_count": ch.token_count,
                            "content_hash": ch.content_hash,
                            "seq": ch.seq,
                            "code": ch.code,  # carried for retrieval rendering (feat-006)
                        },
                        provenance=prov,
                    )
                )
                for target in ch.symbol_ids or [file_id]:
                    graph_items.append(
                        Edge(src=ch.id, dst=target, kind=EdgeKind.CHUNK_OF, provenance=prov)
                    )
            await store.graph.add(graph_items)

            await store.vectors.delete_where({"path": sf.path})  # clean-replace this file
            vectors = await self.embedder.embed([c.text for c in chunks], input_type="document")
            await store.vectors.upsert(
                [
                    Embedded(
                        ref=ch.id,
                        vector=vec,
                        kind=NodeKind.CHUNK,
                        attrs={
                            "path": ch.path,
                            "span": list(ch.span),
                            "symbol_ids": ch.symbol_ids,
                            "model": self.embedder.name,
                        },
                    )
                    for ch, vec in zip(chunks, vectors, strict=True)
                ]
            )
            report.embedded += len(chunks)
        return report
