"""Resolve an ``Embedder`` from ``EmbedConfig`` via the provider registry.

Built-ins (``fake``, ``bedrock``) are registered below; third-party embedders
register out-of-tree under the ``agentforge_graph.embedder_providers`` entry-point
group (``pip install`` + one ``embed.driver`` line, no core change). Bedrock is
imported lazily so the base/fake path never needs boto3.
"""

from __future__ import annotations

from collections.abc import Callable

from agentforge_graph.config import EmbedConfig
from agentforge_graph.providers import resolve_provider

from .base import Embedder

EMBEDDER_GROUP = "agentforge_graph.embedder_providers"

# A builder takes the parsed ``embed:`` block and returns a ready Embedder.
EmbedderBuilder = Callable[[EmbedConfig], Embedder]


def _build_fake(cfg: EmbedConfig) -> Embedder:
    from .fake import FakeEmbedder

    return FakeEmbedder(dim=cfg.dim)


def _build_bedrock(cfg: EmbedConfig) -> Embedder:
    from .bedrock import BedrockEmbedder  # lazy: only needs boto3 on this path

    return BedrockEmbedder(
        model=cfg.model,
        region=cfg.region,
        dim=cfg.dim,
        batch_size=cfg.batch_size,
        assume_role_arn=cfg.assume_role_arn or None,
    )


_EMBEDDER_BUILTINS: dict[str, EmbedderBuilder] = {
    "fake": _build_fake,
    "bedrock": _build_bedrock,
}


def embedder_from_config(cfg: EmbedConfig) -> Embedder:
    """Construct the ``Embedder`` selected by ``cfg.driver`` via the registry."""
    builder = resolve_provider(cfg.driver, _EMBEDDER_BUILTINS, EMBEDDER_GROUP, role="embedder")
    return builder(cfg)
