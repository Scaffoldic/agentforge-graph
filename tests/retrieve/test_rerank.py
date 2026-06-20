"""ENH-009: the lexical (subtoken) + cross-encoder rerankers."""

from __future__ import annotations

import sys
import types

import pytest

from agentforge_graph.core import NodeKind, Source
from agentforge_graph.retrieve.pack import ContextItem
from agentforge_graph.retrieve.rerank import (
    CrossEncoderReranker,
    LexicalReranker,
    NoopReranker,
    SentenceTransformerScorer,
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


def test_resolve_cross_encoder_is_lazy() -> None:
    # resolving cross_encoder must NOT import torch / load a model (CI-safe)
    rr = reranker_from_config("cross_encoder", weight=0.5, model="custom/model")
    assert isinstance(rr, CrossEncoderReranker)


class _KeywordScorer:
    """A fake CrossScorer: high logit when the candidate mentions 'parse'."""

    def score(self, query: str, texts: list[str]) -> list[float]:
        return [5.0 if "parse" in t else -5.0 for t in texts]


async def test_cross_encoder_promotes_the_relevant_candidate() -> None:
    a = _item("a", "chunk1", 0.50, code="formatting helpers and stream shims")
    b = _item("b", "chunk2", 0.45, code="class ZodObject { _parse(input) {} }")
    out = await CrossEncoderReranker(_KeywordScorer(), weight=0.5).rerank("parse an object", [a, b])
    assert out[0].id == "b"  # σ(5) blended in beats the 0.05 base gap
    assert any("cross-encoder" in w for w in out[0].why)


async def test_cross_encoder_noop_without_query_or_items() -> None:
    rr = CrossEncoderReranker(_KeywordScorer())
    assert await rr.rerank("", [_item("a", "x", 0.5)]) == [_item("a", "x", 0.5)]
    assert await rr.rerank("q", []) == []


def test_sentence_transformer_scorer_calls_model(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    class _FakeCrossEncoder:
        def __init__(self, name: str) -> None:
            calls["model"] = name

        def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
            calls["pairs"] = pairs
            return [float(len(t)) for _q, t in pairs]

    fake = types.ModuleType("sentence_transformers")
    fake.CrossEncoder = _FakeCrossEncoder  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake)

    scorer = SentenceTransformerScorer("m/x")
    out = scorer.score("q", ["ab", "abcd"])
    assert out == [2.0, 4.0]
    assert calls["model"] == "m/x"
    assert calls["pairs"] == [("q", "ab"), ("q", "abcd")]
    assert scorer.score("q", []) == []  # empty → no model call needed


def test_sentence_transformer_scorer_missing_dep(monkeypatch: pytest.MonkeyPatch) -> None:
    # simulate the `rerank` extra not installed → a clear, actionable error
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(ImportError, match="rerank"):
        SentenceTransformerScorer().score("q", ["t"])


# --- ENH-013: Bedrock-native rerank ----------------------------------------


class _FakeBedrockClient:
    """A fake bedrock-agent-runtime client: returns results sorted by relevance
    (mimicking the real API) — high for candidates mentioning 'parse'."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def rerank(self, **kwargs: object) -> dict[str, object]:
        self.calls.append(kwargs)
        sources = kwargs["sources"]
        scored = []
        for i, s in enumerate(sources):  # type: ignore[arg-type]
            text = s["inlineDocumentSource"]["textDocument"]["text"]  # type: ignore[index]
            scored.append({"index": i, "relevanceScore": 0.9 if "parse" in text else 0.1})
        scored.sort(key=lambda r: -r["relevanceScore"])  # API returns sorted
        return {"results": scored}


def test_bedrock_scorer_maps_relevance_to_logit_in_input_order() -> None:
    from agentforge_graph.retrieve.rerank import BedrockRerankScorer

    client = _FakeBedrockClient()
    scorer = BedrockRerankScorer(model="cohere.rerank-v3-5:0", region="us-east-1", client=client)
    out = scorer.score("parse an object", ["formatting helpers", "def _parse(x): ..."])
    # logits returned in INPUT order, not the API's sorted order
    assert out[0] < 0 < out[1]  # σ(out[1]) ≈ 0.9, σ(out[0]) ≈ 0.1
    # the request used the Rerank model ARN + one query + two inline sources
    cfg = client.calls[0]["rerankingConfiguration"]
    arn = cfg["bedrockRerankingConfiguration"]["modelConfiguration"]["modelArn"]  # type: ignore[index]
    assert arn.endswith("cohere.rerank-v3-5:0")
    assert scorer.score("q", []) == []  # empty → no API call


async def test_bedrock_reranker_promotes_relevant_candidate() -> None:
    from agentforge_graph.retrieve.rerank import BedrockRerankScorer

    scorer = BedrockRerankScorer(client=_FakeBedrockClient())
    a = _item("a", "chunk1", 0.50, code="formatting helpers and stream shims")
    b = _item("b", "chunk2", 0.45, code="class ZodObject { _parse(input) {} }")
    out = await CrossEncoderReranker(scorer, weight=0.5).rerank("parse an object", [a, b])
    assert out[0].id == "b"


def test_resolve_bedrock_rerank_is_lazy() -> None:
    # a `bedrock:` model selects the Bedrock scorer without importing boto3
    from agentforge_graph.retrieve.rerank import BedrockRerankScorer

    rr = reranker_from_config(
        "cross_encoder", weight=0.5, model="bedrock:cohere.rerank-v3-5:0", region="us-east-1"
    )
    assert isinstance(rr, CrossEncoderReranker)
    assert isinstance(rr._scorer, BedrockRerankScorer)
    assert rr._scorer._model == "cohere.rerank-v3-5:0" and rr._scorer._region == "us-east-1"


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
