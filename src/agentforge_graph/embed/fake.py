"""Deterministic, dependency-free embedder for tests and CI — no creds, no
network. Same text always yields the same L2-normalized vector, so retrieval
tests are reproducible."""

from __future__ import annotations

import hashlib
import math
import struct

from .base import Embedder, InputType


class FakeEmbedder(Embedder):
    def __init__(self, dim: int = 256) -> None:
        self.name = "fake"
        self.dim = dim

    async def embed(
        self, texts: list[str], input_type: InputType = "document"
    ) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        buf = b""
        counter = 0
        need = self.dim * 4
        while len(buf) < need:
            buf += hashlib.sha256(text.encode("utf-8") + counter.to_bytes(4, "big")).digest()
            counter += 1
        words = struct.unpack(f">{self.dim}I", buf[:need])
        vals = [(w / 2**32) * 2.0 - 1.0 for w in words]  # finite, in [-1, 1)
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]
