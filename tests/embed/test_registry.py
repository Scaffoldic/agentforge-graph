"""ENH-003: embedder selection goes through the provider registry —
built-in driver, unknown-driver error, and a third-party entry-point driver."""

from __future__ import annotations

import pytest

import agentforge_graph.providers as providers
from agentforge_graph.config import EmbedConfig
from agentforge_graph.embed import embedder_from_config
from agentforge_graph.embed.base import Embedder
from agentforge_graph.embed.fake import FakeEmbedder
from agentforge_graph.providers import ProviderNotFound


def test_builtin_fake_driver() -> None:
    emb = embedder_from_config(EmbedConfig(driver="fake", dim=64))
    assert isinstance(emb, FakeEmbedder)
    assert emb.dim == 64


def test_unknown_driver_raises() -> None:
    with pytest.raises(ProviderNotFound) as exc:
        embedder_from_config(EmbedConfig(driver="does-not-exist"))
    assert "embedder" in str(exc.value)


def test_third_party_embedder_via_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    """A consumer ships an embedder under the group and selects it by name —
    no change to built-ins (the core 'pluggable' guarantee)."""

    class _MyEmbedder(Embedder):
        name = "mine"
        dim = 3

        async def embed(self, texts: list[str], input_type: str = "document") -> list[list[float]]:
            return [[1.0, 2.0, 3.0] for _ in texts]

    def _build(cfg: EmbedConfig) -> Embedder:
        return _MyEmbedder()

    class _EP:
        name = "custom"

        @staticmethod
        def load() -> object:
            return _build

    monkeypatch.setattr(
        providers, "entry_points", lambda *, group: [_EP()] if "embedder" in group else []
    )
    emb = embedder_from_config(EmbedConfig(driver="custom"))
    assert isinstance(emb, _MyEmbedder)
