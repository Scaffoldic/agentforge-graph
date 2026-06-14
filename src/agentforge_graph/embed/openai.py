"""``OpenAIEmbedder`` — OpenAI (and OpenAI-compatible) embeddings (ENH-003
phase 2; the most-requested non-AWS path, and the **local model** path).

Lazy-imports the ``openai`` SDK (the ``openai`` extra); synchronous calls run on
a worker thread, mirroring ``BedrockEmbedder``. Setting ``embed.base_url`` points
the same adapter at any OpenAI-compatible server — a local Ollama
(``http://localhost:11434/v1``), vLLM, LM Studio, or a gateway — so "bring your
own / run it locally" is a config line, not a new adapter.

``text-embedding-3-*`` models support arbitrary output ``dimensions``; ``dim``
is passed through. Credentials come from ``OPENAI_API_KEY`` (the SDK default)
unless ``api_key_env`` overrides it. Imports nothing from ``agentforge``
(ADR-0001).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from .base import Embedder, InputType


class OpenAIEmbedder(Embedder):
    def __init__(
        self,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
        batch_size: int = 96,
        base_url: str = "",
        api_key_env: str = "OPENAI_API_KEY",
    ) -> None:
        self.name = f"openai:{model}"
        self.model = model
        self.dim = dim
        self.batch_size = batch_size
        self.base_url = base_url
        self.api_key_env = api_key_env
        self._client: Any = None

    def _openai(self) -> Any:
        if self._client is None:
            import openai

            kwargs: dict[str, Any] = {}
            key = os.environ.get(self.api_key_env)
            if key:
                kwargs["api_key"] = key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = openai.OpenAI(**kwargs)
        return self._client

    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
        # OpenAI embeddings are symmetric — ``input_type`` is ignored.
        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            out.extend(await asyncio.to_thread(self._invoke, batch))
        return out

    def _invoke(self, batch: list[str]) -> list[list[float]]:
        resp = self._openai().embeddings.create(model=self.model, input=batch, dimensions=self.dim)
        return [[float(x) for x in item.embedding] for item in resp.data]
