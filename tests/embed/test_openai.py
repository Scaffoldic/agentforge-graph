"""OpenAI embedder (ENH-003 phase 2) — deterministic, no network/SDK required.

Covers registry resolution, batching, dimension pass-through, and the lazy SDK
build (via a fake ``openai`` module) including the ``base_url`` / api-key path
that makes a local OpenAI-compatible server a config line."""

from __future__ import annotations

import sys
import types
from typing import Any

from agentforge_graph.config import EmbedConfig
from agentforge_graph.embed import embedder_from_config
from agentforge_graph.embed.openai import OpenAIEmbedder


class _Item:
    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _Resp:
    def __init__(self, data: list[_Item]) -> None:
        self.data = data


class _FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str], int]] = []

    def create(self, model: str, input: list[str], dimensions: int) -> _Resp:
        self.calls.append((model, list(input), dimensions))
        return _Resp([_Item([0.1, 0.2, 0.3]) for _ in input])


class _FakeOpenAI:
    def __init__(self) -> None:
        self.embeddings = _FakeEmbeddings()


def test_registry_resolves_openai_and_metadata() -> None:
    emb = embedder_from_config(
        EmbedConfig(driver="openai", model="text-embedding-3-large", dim=256)
    )
    assert isinstance(emb, OpenAIEmbedder)
    assert emb.name == "openai:text-embedding-3-large"
    assert emb.dim == 256


async def test_embed_batches_and_passes_dimensions() -> None:
    emb = OpenAIEmbedder(model="text-embedding-3-small", dim=3, batch_size=2)
    emb._client = _FakeOpenAI()  # bypass the lazy SDK import
    out = await emb.embed(["a", "b", "c"], input_type="query")  # input_type ignored
    assert len(out) == 3 and all(len(v) == 3 for v in out)
    calls = emb._client.embeddings.calls
    assert len(calls) == 2  # batched 2 + 1
    assert calls[0][2] == 3  # dimensions threaded through


def test_lazy_build_uses_base_url_and_key(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    fake_openai = types.ModuleType("openai")

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_openai.OpenAI = _Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake_openai)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-x")

    emb = OpenAIEmbedder(base_url="http://localhost:11434/v1")
    client = emb._openai()
    assert client is not None
    assert emb._openai() is client  # cached
    assert captured["api_key"] == "sk-x"
    assert captured["base_url"] == "http://localhost:11434/v1"
