"""feat-010: ADR/doc (`source_type: doc`) vector hits are down-weighted so code
outranks equally-similar prose by default — unless the query smells architectural,
where docs keep their full score. Mitigates doc-volume dilution (spec §8)."""

from __future__ import annotations

from agentforge_graph.retrieve.retriever import _is_architectural


def test_architectural_queries_detected() -> None:
    assert _is_architectural("why is auth built this way?")
    assert _is_architectural("what decision governs payments")
    assert _is_architectural("the idempotency CONVENTION")  # case-insensitive
    assert _is_architectural("ADR for retries")


def test_plain_queries_not_architectural() -> None:
    assert not _is_architectural("charge a credit card")
    assert not _is_architectural("parse the timestamp")
    assert not _is_architectural("list users by id")


async def test_doc_hit_is_down_weighted(tmp_path: object) -> None:
    # a doc chunk and a code chunk with the SAME text get the same raw similarity;
    # the doc one must score lower after the default doc_weight penalty.
    import hashlib
    from pathlib import Path

    from agentforge_graph.config import RetrieveConfig
    from agentforge_graph.core import Embedded, NodeKind, Provenance, SourceFile, SymbolID
    from agentforge_graph.core import Node as GNode
    from agentforge_graph.embed import FakeEmbedder
    from agentforge_graph.ingest import TreeSitterExtractor
    from agentforge_graph.ingest.packs.python import PYTHON_PACK
    from agentforge_graph.retrieve import Retriever
    from agentforge_graph.store import Store

    tp = Path(str(tmp_path))
    store = await Store.open(tp / "s", config=None)
    try:
        # one real code symbol (so the graph has a File + symbol)
        ex = TreeSitterExtractor(PYTHON_PACK, repo="fix")
        text = "def handler():\n    return 1\n"
        sf = SourceFile(
            path="m.py", text=text, language="py", content_hash=hashlib.sha256(b"m").hexdigest()
        )
        await store.graph.upsert(ex.extract(sf))
        # a doc chunk node + a code chunk node sharing the same prose
        prose = "shared prose about handling"
        doc_id = SymbolID.for_symbol("doc", "fix", "d.md", "docchunk(0).")
        code_ref = SymbolID.for_symbol("py", "fix", "m.py", "handler().chunk(0).")
        await store.graph.add(
            [
                GNode(
                    id=doc_id,
                    kind=NodeKind.DOC_CHUNK,
                    name="d",
                    attrs={"path": "d.md", "text": prose, "heading": ""},
                    provenance=Provenance.parsed("t"),
                ),
                GNode(
                    id=code_ref,
                    kind=NodeKind.CHUNK,
                    name="chunk0",
                    attrs={"path": "m.py", "code": prose},
                    provenance=Provenance.parsed("t"),
                ),
            ]
        )
        emb = FakeEmbedder(dim=24)
        [vec] = await emb.embed([prose], "document")
        # same vector for the code chunk ref and the doc ref → identical raw similarity
        await store.vectors.upsert(
            [
                Embedded(ref=doc_id, vector=vec, kind=NodeKind.DOC_CHUNK, attrs={"path": "d.md"}),
                Embedded(ref=code_ref, vector=vec, kind=NodeKind.CHUNK, attrs={"path": "m.py"}),
            ]
        )

        r = Retriever(store, emb, RetrieveConfig(k=5, depth=0, doc_weight=0.5))
        pack = await r.retrieve(prose, mode="similar")  # plain query → docs penalised
        by_id = {it.id: it.score for it in pack.items}
        assert by_id[doc_id] < by_id[code_ref]  # doc down-weighted below the code chunk

        pack2 = await r.retrieve(f"why {prose} design", mode="similar")  # architectural
        by_id2 = {it.id: it.score for it in pack2.items}
        assert by_id2[doc_id] == by_id2[code_ref]  # full score — no penalty
    finally:
        await store.close()
