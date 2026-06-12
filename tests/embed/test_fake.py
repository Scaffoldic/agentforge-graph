"""FakeEmbedder determinism + the config registry."""

from __future__ import annotations

import math

import pytest

from agentforge_graph.config import EmbedConfig
from agentforge_graph.embed import FakeEmbedder, embedder_from_config


async def test_deterministic_and_dim() -> None:
    e = FakeEmbedder(dim=64)
    a = await e.embed(["def f(): pass"])
    b = await e.embed(["def f(): pass"])
    assert a == b
    assert len(a[0]) == 64


async def test_normalized() -> None:
    [vec] = await FakeEmbedder(dim=128).embed(["hello world"])
    assert math.isclose(math.sqrt(sum(v * v for v in vec)), 1.0, rel_tol=1e-6)
    assert all(math.isfinite(v) for v in vec)


async def test_distinct_texts_distinct_vectors() -> None:
    e = FakeEmbedder(dim=32)
    [va], [vb] = await e.embed(["alpha"]), await e.embed(["beta"])
    assert va != vb


async def test_batch_matches_singletons() -> None:
    e = FakeEmbedder(dim=16)
    batch = await e.embed(["a", "b", "c"])
    singles = [(await e.embed([t]))[0] for t in ("a", "b", "c")]
    assert batch == singles


def test_registry_fake() -> None:
    e = embedder_from_config(EmbedConfig(driver="fake", dim=48))
    assert isinstance(e, FakeEmbedder)
    assert e.dim == 48


def test_registry_unknown_driver() -> None:
    with pytest.raises(ValueError, match="unknown embed driver"):
        embedder_from_config(EmbedConfig(driver="nope"))
