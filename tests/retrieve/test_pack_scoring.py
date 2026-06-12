"""ContextPack rendering + scoring math."""

from __future__ import annotations

from agentforge_graph.chunking import estimate_tokens
from agentforge_graph.core import NodeKind, Source
from agentforge_graph.retrieve import ContextItem, ContextPack
from agentforge_graph.retrieve.scoring import dedupe_max, edge_weight, step_score


def _item(
    id: str, score: float, code: str | None = None, why: list[str] | None = None
) -> ContextItem:
    return ContextItem(
        id=f"ckg py r f.py {id}.",
        kind=NodeKind.FUNCTION,
        name=id,
        score=score,
        path="f.py",
        span=(1, 3),
        code=code,
        provenance=Source.PARSED,
        why=why or [],
    )


def test_edge_weight_by_provenance() -> None:
    w = {"resolved": 1.0, "parsed": 0.5, "llm": 0.3}
    assert edge_weight(w, Source.RESOLVED) == 1.0
    assert edge_weight(w, Source.PARSED) == 0.5
    assert edge_weight(w, Source.MANUAL) == 0.5  # fallback


def test_step_score_decays() -> None:
    s1 = step_score(1.0, 0.6, 1.0)
    s2 = step_score(s1, 0.6, 1.0)
    assert s1 == 0.6
    assert round(s2, 3) == 0.36  # decay^2


def test_dedupe_keeps_max_and_unions_why() -> None:
    a = _item("f", 0.4, why=["vector hit"])
    b = _item("f", 0.9, why=["CALLS of g (hop 1)"])
    [merged] = dedupe_max([a, b])
    assert merged.score == 0.9
    assert set(merged.why) == {"vector hit", "CALLS of g (hop 1)"}


def test_dedupe_sorts_descending() -> None:
    out = dedupe_max([_item("a", 0.2), _item("b", 0.9), _item("c", 0.5)])
    assert [i.name for i in out] == ["b", "c", "a"]


def test_render_highest_first_and_within_budget() -> None:
    pack = ContextPack(
        items=[
            _item("hi", 0.9, code="def hi():\n    return 1"),
            _item("lo", 0.1, code="def lo():\n    return 2"),
        ]
    )
    rendered = pack.render(budget_tokens=10_000)
    assert rendered.index("hi") < rendered.index("lo")


def test_render_degrades_to_signature_over_budget() -> None:
    big = "x = 1\n" * 200
    item = _item("big", 0.9, code=big)
    pack = ContextPack(items=[item])
    budget = estimate_tokens(item.signature()) + 5  # fits the signature, not the code
    rendered = pack.render(budget_tokens=budget)
    assert "x = 1" not in rendered  # the full code block did not fit
    assert "big" in rendered  # signature still present


def test_render_never_splits_a_chunk() -> None:
    code = "\n".join(f"line{i} = {i}" for i in range(40))
    pack = ContextPack(items=[_item("c", 0.9, code=code)])
    rendered = pack.render(budget_tokens=estimate_tokens(code) // 2)
    # either the whole code block is present, or none of its body lines are
    assert ("line39" in rendered) == ("line0" in rendered)


def test_to_dict_roundtrips() -> None:
    pack = ContextPack(query="q", items=[_item("f", 0.5)], notes=["fan-out cap hit"])
    d = pack.to_dict()
    assert d["query"] == "q"
    assert d["items"][0]["name"] == "f"
    assert d["notes"] == ["fan-out cap hit"]
