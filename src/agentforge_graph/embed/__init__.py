"""agentforge_graph.embed — chunk embedding (feat-005).

Default real backend is AWS Bedrock Cohere embed-v4 (`BedrockEmbedder`);
`OpenAIEmbedder` is the non-AWS / local-server path (ENH-003 phase 2); tests/CI
use the deterministic `FakeEmbedder`. Imports nothing from ``agentforge``
(ADR-0001); each driver's SDK (boto3 / openai) is lazy-imported in its module.
"""

from __future__ import annotations

from .base import Embedder, InputType
from .bedrock import BedrockEmbedder
from .fake import FakeEmbedder
from .openai import OpenAIEmbedder
from .pipeline import EmbedPipeline
from .registry import embedder_from_config
from .report import EmbedReport

__all__ = [
    "Embedder",
    "InputType",
    "FakeEmbedder",
    "BedrockEmbedder",
    "OpenAIEmbedder",
    "EmbedPipeline",
    "EmbedReport",
    "embedder_from_config",
]
