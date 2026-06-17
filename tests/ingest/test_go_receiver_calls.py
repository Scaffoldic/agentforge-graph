"""BUG-006 — Go: a call on a method's own receiver (`s.f()`) resolves to a method
of the receiver's *type* (not a same-named method of another type, nor a
package-level func). Go's receiver is a named variable, not a `self`/`this`
keyword, so it needs the per-method receiver var + type."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SourceFile
from agentforge_graph.ingest import ImportResolver, PackRegistry, TreeSitterExtractor
from agentforge_graph.ingest.packs import GO_PACK
from agentforge_graph.store import KuzuGraphStore


async def _resolve(tmp_path: Path, files: dict[str, str]) -> KuzuGraphStore:
    store = await KuzuGraphStore.open(tmp_path / "g.kuzu")
    extractor = TreeSitterExtractor(GO_PACK, repo="fixture")
    for rel, text in files.items():
        sf = SourceFile(
            path=rel,
            text=text,
            language="go",
            content_hash=hashlib.sha256(text.encode()).hexdigest(),
        )
        await store.upsert(extractor.extract(sf))
    await ImportResolver(PackRegistry([GO_PACK])).resolve(store)
    return store


async def _calls_id(store: KuzuGraphStore, caller_id: str) -> set[str]:
    return {n.id for n in await store.neighbors(caller_id, [EdgeKind.CALLS], depth=1)}


async def test_receiver_call_resolves_to_type_method(tmp_path: Path) -> None:
    # two types each with `other`; Server.Handle()'s self-call must bind to
    # Server.other, never Client.other (precision).
    src = (
        "package m\n\n"
        "type Server struct{}\n"
        "func (s *Server) Handle() int { return s.other() }\n"
        "func (s *Server) other() int { return 1 }\n\n"
        "type Client struct{}\n"
        "func (c *Client) other() int { return 2 }\n"
    )
    store = await _resolve(tmp_path, {"m.go": src})
    try:
        nodes = (await store.query(GraphQuery(kinds=[NodeKind.METHOD], limit=100))).nodes
        handle = next(n for n in nodes if n.name == "Handle")
        # the Server.other (its receiver type is Server) — find it via recv_type
        server_other = next(
            n for n in nodes if n.name == "other" and n.attrs.get("recv_type") == "Server"
        )
        client_other = next(
            n for n in nodes if n.name == "other" and n.attrs.get("recv_type") == "Client"
        )
        called = await _calls_id(store, handle.id)
        assert server_other.id in called  # resolves to the receiver type's method
        assert client_other.id not in called  # not the other type's same-named method
    finally:
        await store.close()


async def test_value_receiver_resolves(tmp_path: Path) -> None:
    src = (
        "package m\n\n"
        "type T struct{}\n"
        "func (t T) run() int { return t.helper() }\n"  # value receiver (no pointer)
        "func (t T) helper() int { return 1 }\n"
    )
    store = await _resolve(tmp_path, {"m.go": src})
    try:
        nodes = (await store.query(GraphQuery(kinds=[NodeKind.METHOD], limit=100))).nodes
        run = next(n for n in nodes if n.name == "run")
        helper = next(n for n in nodes if n.name == "helper")
        assert helper.id in await _calls_id(store, run.id)
    finally:
        await store.close()
