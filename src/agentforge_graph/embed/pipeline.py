"""``EmbedPipeline`` — chunk the indexed code and embed the chunks.

Per file: pull its symbol nodes from the graph, chunk them, write `CHUNK`
nodes + `CHUNK_OF` edges, embed the chunk texts, and upsert vectors. Coarse
incrementality at 0.1: if a file's chunk-hash set is unchanged, skip
re-embedding (saves cost); otherwise clean-replace the file's chunk vectors.
feat-004 will scope this to a DirtySet.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

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

    async def run(
        self,
        store: Store,
        source: RepoSource,
        registry: PackRegistry,
        only_paths: set[str] | None = None,
        doc_root: Path | None = None,
    ) -> EmbedReport:
        """Embed the indexed code. When ``only_paths`` is given (feat-004: the
        files a refresh dirtied), only those files are re-chunked/embedded;
        otherwise every file is visited (the chunk-hash skip still avoids
        re-embedding unchanged files)."""
        report = EmbedReport(model=self.embedder.name, dim=self.embedder.dim)
        prov = Provenance.parsed(self.name, self.commit)

        for sf in source.iter_files(registry):
            if only_paths is not None and sf.path not in only_paths:
                continue
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
                            "source_type": "code",  # vs "doc" (feat-010) — lets
                            "model": self.embedder.name,  # retrieval tell them apart
                        },
                    )
                    for ch, vec in zip(chunks, vectors, strict=True)
                ]
            )
            report.embedded += len(chunks)

        report.doc_chunks = await self._embed_docs(store, doc_root)
        return report

    async def _embed_docs(self, store: Store, doc_root: Path | None = None) -> int:
        """Embed ADR/doc ``DocChunk`` prose so an architectural query surfaces the
        governing decision / documented symbol (feat-010). A ``source_type: doc``
        tag keeps these distinct from code chunks. Incremental: a fingerprint of all
        doc chunks (ids + content hashes + embedder) is recorded under ``doc_root``;
        when it is unchanged the whole pass is skipped (no API calls). On any change
        it clean-replaces every doc vector (the simple, orphan-safe path for the
        small doc set)."""
        docs = (await store.graph.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=_ALL))).nodes
        manifest = (doc_root / "doc_embed.hash") if doc_root is not None else None
        if not docs:
            await store.vectors.delete_where({"kind": NodeKind.DOC_CHUNK.value})
            if manifest is not None and manifest.exists():
                manifest.unlink()
            return 0
        fp_body = "".join(
            f"{n.id}|{n.attrs.get('content_hash', '')};" for n in sorted(docs, key=lambda z: z.id)
        )
        fingerprint = hashlib.sha256(
            f"{self.embedder.name}:{self.embedder.dim}:{fp_body}".encode()
        ).hexdigest()
        if (
            manifest is not None
            and manifest.exists()
            and manifest.read_text().strip() == fingerprint
        ):
            return 0  # docs unchanged since the last embed → skip the re-embed
        # clean-replace via the DocChunk kind (a filterable vector column) — this
        # also GCs vectors for docs/ADRs that were removed since the last embed.
        await store.vectors.delete_where({"kind": NodeKind.DOC_CHUNK.value})
        texts = [f"{n.attrs.get('heading', '')}\n{n.attrs.get('text', '')}".strip() for n in docs]
        vectors = await self.embedder.embed(texts, input_type="document")
        await store.vectors.upsert(
            [
                Embedded(
                    ref=n.id,
                    vector=vec,
                    kind=NodeKind.DOC_CHUNK,
                    attrs={
                        "path": n.attrs.get("path", ""),
                        "source_type": "doc",
                        "heading": n.attrs.get("heading", ""),
                        "model": self.embedder.name,
                    },
                )
                for n, vec in zip(docs, vectors, strict=True)
            ]
        )
        if manifest is not None:
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(fingerprint)
        return len(docs)
