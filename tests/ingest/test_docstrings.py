"""feat-010 follow-up: a Python symbol's docstring becomes a ``DocChunk`` that
``DESCRIBES`` the symbol — so the docstring prose is its own searchable node,
attached to the exact function/class/method it documents. Symbols without a
leading docstring get no DocChunk."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile, SymbolID
from agentforge_graph.ingest import TreeSitterExtractor
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.store import KuzuGraphStore

SRC = '''\
class Service:
    """Charges cards idempotently per key."""

    def charge(self, amount):
        """Charge a card; safe to retry with the same key."""
        return amount

    def _helper(self):
        return 1


def free_fn():
    """A free function with docs."""
    return 0


def undocumented():
    x = "not a docstring"
    return x
'''


async def _extract(tmp_path: Path) -> KuzuGraphStore:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    ex = TreeSitterExtractor(PYTHON_PACK, repo="fixture")
    sf = SourceFile(
        path="svc.py",
        text=SRC,
        language="py",
        content_hash=hashlib.sha256(SRC.encode()).hexdigest(),
    )
    await store.upsert(ex.extract(sf))
    return store


async def _doc_chunks(store: KuzuGraphStore) -> list[object]:
    return (await store.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=999))).nodes


async def test_docstring_becomes_describing_docchunk(tmp_path: Path) -> None:
    store = await _extract(tmp_path)
    try:
        docs = await _doc_chunks(store)
        # one DocChunk each for Service, charge, free_fn — NOT _helper/undocumented
        described = set()
        for d in docs:
            outs = await store.adjacent(d.id, [EdgeKind.DESCRIBES], "out")
            assert outs, f"DocChunk {d.id} has no DESCRIBES edge"
            described.add(SymbolID.parse(outs[0].dst).descriptor)
        assert "Service#" in described
        assert "Service#charge()." in described
        assert "free_fn()." in described
        assert not any("undocumented" in d for d in described)
        assert not any("_helper" in d for d in described)
    finally:
        await store.close()


async def test_docstring_text_is_cleaned(tmp_path: Path) -> None:
    store = await _extract(tmp_path)
    try:
        docs = await _doc_chunks(store)
        texts = {d.attrs.get("text") for d in docs}
        assert "Charges cards idempotently per key." in texts  # quotes stripped, trimmed
        # no triple quotes leaked into the body
        assert all('"""' not in (d.attrs.get("text") or "") for d in docs)
    finally:
        await store.close()


async def test_undocumented_symbol_has_no_docchunk(tmp_path: Path) -> None:
    store = await _extract(tmp_path)
    try:
        # the module-level string `x = "..."` inside undocumented() is NOT a docstring
        docs = await _doc_chunks(store)
        assert len(docs) == 3  # Service, charge, free_fn
    finally:
        await store.close()


async def test_describes_in_default_retrieval(tmp_path: Path) -> None:
    # a docstring-prose query seeds the symbol it DESCRIBES (FakeEmbedder exact hit)
    import shutil

    from agentforge_graph.config import RetrieveConfig
    from agentforge_graph.embed import FakeEmbedder
    from agentforge_graph.ingest import CodeGraph
    from agentforge_graph.retrieve import Retriever

    repo = tmp_path / "proj"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "svc.py").write_text(SRC)
    shutil.rmtree(tmp_path / "g.kuzu", ignore_errors=True)
    cg = await CodeGraph.index(repo_path=repo)
    emb = FakeEmbedder(dim=32)
    await cg.embed(embedder=emb)
    try:
        docs = await _doc_chunks(cg.store.graph)
        target = next(d for d in docs if "retry" in (d.attrs.get("text") or ""))
        text = f"{target.attrs.get('heading', '')}\n{target.attrs.get('text', '')}".strip()
        r = Retriever(cg.store, emb, RetrieveConfig(k=5, depth=1))
        pack = await r.retrieve(text, mode="context")
        descs = {SymbolID.parse(it.id).descriptor for it in pack.items}
        assert any(d.endswith("charge().") for d in descs)  # the described method surfaced
    finally:
        await cg.close()
