"""Provenance filtering and fan-out capping."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from agentforge_graph.config import RetrieveConfig
from agentforge_graph.core import Edge, EdgeKind, Node, NodeKind, Provenance, Source, SymbolID
from agentforge_graph.embed import FakeEmbedder
from agentforge_graph.retrieve import ContextItem, Retriever
from agentforge_graph.store import Store


def _ci(name: str, source: Source) -> ContextItem:
    prov = {
        Source.PARSED: Provenance.parsed("t"),
        Source.RESOLVED: Provenance.resolved("t"),
        Source.MANUAL: Provenance.manual("t"),
        Source.LLM: Provenance.llm("t", 0.9),
    }[source]
    return ContextItem(
        id=f"ckg py r f.py {name}.",
        kind=NodeKind.FUNCTION,
        name=name,
        score=1.0,
        path="f.py",
        provenance=prov.source,
    )


def _retriever() -> Retriever:
    return Retriever(cast(Any, None), cast(Any, None), RetrieveConfig())


def test_min_provenance_resolved_keeps_resolved_and_manual() -> None:
    items = [_ci("p", Source.PARSED), _ci("r", Source.RESOLVED), _ci("m", Source.MANUAL)]
    out = _retriever()._filter(items, "resolved", include_llm_facts=True)
    assert {i.name for i in out} == {"r", "m"}


def test_min_provenance_parsed_excludes_llm() -> None:
    items = [_ci("p", Source.PARSED), _ci("l", Source.LLM)]
    out = _retriever()._filter(items, "parsed", include_llm_facts=True)
    assert {i.name for i in out} == {"p"}


def test_include_llm_facts_false_drops_llm() -> None:
    items = [_ci("p", Source.PARSED), _ci("l", Source.LLM)]
    out = _retriever()._filter(items, None, include_llm_facts=False)
    assert all(i.provenance is not Source.LLM for i in out)


async def test_fanout_cap_recorded_in_notes(tmp_path: Path) -> None:
    store = await Store.open(repo_path=tmp_path)
    try:
        prov = Provenance.parsed("t")
        hub = SymbolID.for_symbol("py", "r", "h.py", "hub().")
        items: list[Node | Edge] = [
            Node(id=hub, kind=NodeKind.FUNCTION, name="hub", provenance=prov)
        ]
        for i in range(30):
            t = SymbolID.for_symbol("py", "r", "h.py", f"t{i}().")
            items.append(Node(id=t, kind=NodeKind.FUNCTION, name=f"t{i}", provenance=prov))
            items.append(Edge(src=hub, dst=t, kind=EdgeKind.CALLS, provenance=prov))
        await store.graph.add(items)
        r = Retriever(store, FakeEmbedder(dim=8), RetrieveConfig(fanout_cap=5))
        pack = await r.retrieve(symbol=hub, mode="context", depth=1)
        assert any("fan-out cap 5" in n for n in pack.notes)
    finally:
        await store.close()
