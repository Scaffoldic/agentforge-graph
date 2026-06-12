"""agentforge_graph.embed — chunk embedding (feat-005).

Default real backend is AWS Bedrock Cohere embed-v4 (`BedrockEmbedder`);
tests/CI use the deterministic `FakeEmbedder`. Imports nothing from
``agentforge`` (ADR-0001); boto3 is isolated to the Bedrock driver.
"""

from __future__ import annotations

from .base import Embedder, InputType
from .bedrock import BedrockEmbedder
from .fake import FakeEmbedder
from .registry import embedder_from_config

__all__ = [
    "Embedder",
    "InputType",
    "FakeEmbedder",
    "BedrockEmbedder",
    "embedder_from_config",
]
