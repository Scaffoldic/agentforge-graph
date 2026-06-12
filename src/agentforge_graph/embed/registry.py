"""Resolve an ``Embedder`` from ``EmbedConfig``. Bedrock is imported lazily
so the base/fake path never needs boto3."""

from __future__ import annotations

from agentforge_graph.config import EmbedConfig

from .base import Embedder
from .fake import FakeEmbedder


def embedder_from_config(cfg: EmbedConfig) -> Embedder:
    if cfg.driver == "fake":
        return FakeEmbedder(dim=cfg.dim)
    if cfg.driver == "bedrock":
        from .bedrock import BedrockEmbedder  # lazy: only needs boto3 on this path

        return BedrockEmbedder(
            model=cfg.model,
            region=cfg.region,
            dim=cfg.dim,
            batch_size=cfg.batch_size,
            assume_role_arn=cfg.assume_role_arn or None,
        )
    raise ValueError(f"unknown embed driver {cfg.driver!r} (known: fake, bedrock)")
