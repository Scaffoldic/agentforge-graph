"""Reranking hook. The default is identity; a concrete cross-encoder
reranker is a post-0.1 adapter that lives *outside* this package so the
retrieval core stays framework-free (ADR-0001)."""

from __future__ import annotations

from typing import Protocol

from .pack import ContextItem


class Reranker(Protocol):
    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]: ...


class NoopReranker:
    """Identity reranker (rerank: off)."""

    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]:
        return items
