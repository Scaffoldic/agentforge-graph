"""The ``Chunk`` value — a retrieval artifact distinct from the symbol nodes
it covers (the chunk↔symbol separation that lets a vector hit expand into the
graph; feat-006). Converts to a ``CHUNK`` node + ``CHUNK_OF`` edges."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Chunk(BaseModel):
    id: str  # SymbolID with a chunk(<seq>). descriptor on the file path
    text: str  # embedding text: "<path> | <symbol>\n<code>"
    code: str  # raw source slice (for display)
    token_count: int
    path: str
    span: tuple[int, int]  # 1-based inclusive line range
    content_hash: str  # sha256(text + chunker params) — the vector key
    symbol_ids: list[str] = Field(default_factory=list)  # CHUNK_OF targets
    seq: int  # order within the file
