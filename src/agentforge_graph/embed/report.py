"""Result type for an embedding run."""

from __future__ import annotations

from pydantic import BaseModel


class EmbedReport(BaseModel):
    files: int = 0
    chunks: int = 0
    embedded: int = 0
    skipped_unchanged: int = 0  # files whose chunk set was unchanged (hash-skip)
    model: str = ""
    dim: int = 0
