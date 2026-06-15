"""ENH-009: the deterministic lexical reranker — subtoken overlap blend."""

from __future__ import annotations

import pytest

from agentforge_graph.core import NodeKind, Source
from agentforge_graph.retrieve.pack import ContextItem
from agentforge_graph.retrieve.rerank import (
    LexicalReranker,
    NoopReranker,
    _tokens,
    reranker_from_config,
)


def _item(id: str, name: str, score: float, code: str = "") -> ContextItem:
    return ContextItem(
        id=id, kind=NodeKind.CHUNK, name=name, score=score, path="a.ts",
        code=code, provenance=Source.PARSED,
    )  # fmt: skip


def test_tokens_splits_camel_snake_dotted() -> None:
    assert _tokens("ZodObject._parse") == {"zod", "object", "parse"}
    assert _tokens("res.send") == {"res", "send"}
    assert _tokens("how is an object parsed") == {"object", "parsed"}  # stopwords dropped


def test_resolve_off_and_lexical() -> None:
    assert isinstance(reranker_from_config("off"), NoopReranker)
    assert isinstance(reranker_from_config(""), NoopReranker)
    assert isinstance(reranker_from_config("lexical"), LexicalReranker)
    with pytest.raises(ValueError, match="unknown reranker"):
        reranker_from_config("magic")


async def test_lexical_promotes_the_token_match() -> None:
    # two chunks: A has a slightly higher cosine but no term overlap; B mentions
    # the queried symbol. The lexical blend should surface B.
    a = _item("a", "chunk1", 0.50, code="formatting helpers and stream shims")
    b = _item("b", "chunk2", 0.45, code="class ZodObject { _parse(input) { } }")
    out = await LexicalReranker(weight=0.5).rerank("how is an object parsed", [a, b])
    assert out[0].id == "b"  # term overlap (object, parse) outweighs the 0.05 cosine gap
    assert any("lexical" in w for w in out[0].why)


async def test_lexical_is_noop_without_query_or_items() -> None:
    rr = LexicalReranker()
    assert await rr.rerank("", [_item("a", "x", 0.5)]) == [_item("a", "x", 0.5)]
    assert await rr.rerank("q", []) == []


async def test_lexical_is_deterministic_and_stable() -> None:
    items = [_item("a", "n", 0.4, "foo"), _item("b", "n", 0.4, "foo")]
    out1 = await LexicalReranker().rerank("bar", items)
    out2 = await LexicalReranker().rerank("bar", items)
    assert [i.id for i in out1] == [i.id for i in out2] == ["a", "b"]  # id tiebreak
