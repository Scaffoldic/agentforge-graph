"""The ``Embedder`` contract. Implementations: ``FakeEmbedder`` (CI default,
deterministic) and ``BedrockEmbedder`` (Cohere embed-v4). Imports nothing
from ``agentforge`` (ADR-0001)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Literal

InputType = Literal["document", "query"]


class Embedder(ABC):
    name: str
    dim: int

    @abstractmethod
    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
        """Embed ``texts``. ``input_type`` distinguishes stored documents from
        search queries (asymmetric models use it; symmetric ones ignore it)."""
