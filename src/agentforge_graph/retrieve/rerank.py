"""Reranking hook (feat-006 seam; ENH-009).

The default is identity (``rerank: off``). ``rerank: lexical`` enables a
deterministic, dependency-free **lexical reranker**: it blends each candidate's
vector/graph score with the **subtoken overlap** between the query and the
candidate's name + code, so a chunk whose symbol the query names (``ZodObject``,
``_parse``, ``res.send``) sorts up even when its raw cosine landed *near* the
answer. No model, no API — a "poor man's cross-encoder" that sharpens the common
"ask for a symbol, get it" case. A heavyweight cross-encoder remains a post-0.1
out-of-tree adapter (ADR-0001)."""

from __future__ import annotations

import re
from typing import Protocol

from .pack import ContextItem

# Function words that carry no retrieval signal — dropped from both sides.
_STOP = frozenset(
    [
        "a",
        "an",
        "the",
        "is",
        "are",
        "was",
        "were",
        "be",
        "how",
        "do",
        "does",
        "did",
        "of",
        "to",
        "in",
        "on",
        "for",
        "and",
        "or",
        "with",
        "this",
        "that",
        "it",
        "as",
        "at",
        "by",
        "from",
        "into",
        "than",
        "then",
        "over",
        "under",
        "not",
        "no",
        "your",
        "you",
        "we",
        "i",
        "me",
        "my",
        "our",
        "their",
        "its",
        "they",
        "them",
        "he",
        "she",
        "where",
        "what",
        "which",
        "who",
        "when",
        "why",
        "can",
        "could",
        "should",
        "would",
        "will",
        "shall",
        "may",
        "might",
        "must",
        "have",
        "has",
        "had",
        "get",
        "set",
        "up",
        "out",
        "off",
        "via",
        "per",
        "use",
        "used",
        "using",
        "return",
        "returns",
    ]
)
# Split identifiers into subtokens: ALLCAPS, CamelChunk, or a run of lower/digits.
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Lowercased subtokens of ``text``: splits on non-alphanumerics *and*
    camelCase, so ``ZodObject._parse`` → {zod, object, parse}. Drops stopwords
    and single chars (noise)."""
    out: set[str] = set()
    for raw in re.split(r"[^A-Za-z0-9]+", text):
        for m in _CAMEL.findall(raw):
            low = m.lower()
            if len(low) >= 2 and low not in _STOP:
                out.add(low)
    return out


class Reranker(Protocol):
    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]: ...


class NoopReranker:
    """Identity reranker (rerank: off)."""

    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]:
        return items


class LexicalReranker:
    """Blend base score with query↔candidate subtoken overlap, then re-sort.

    ``final = (1 - weight)·base + weight·overlap``, where ``overlap`` is the
    fraction of (non-stopword) query subtokens present in the candidate's
    name + code. Deterministic and order-stable on ties."""

    def __init__(self, weight: float = 0.5) -> None:
        self._w = max(0.0, min(1.0, weight))

    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]:
        qtoks = _tokens(query)
        if not qtoks or not items:
            return items
        rescored: list[ContextItem] = []
        for it in items:
            itoks = _tokens(f"{it.name} {it.code or ''}")
            overlap = len(qtoks & itoks) / len(qtoks)
            final = (1.0 - self._w) * it.score + self._w * overlap
            rescored.append(
                it.model_copy(update={"score": final, "why": [*it.why, f"lexical {overlap:.2f}"]})
            )
        rescored.sort(key=lambda i: (-i.score, i.id))  # id tiebreak = deterministic
        return rescored


def reranker_from_config(rerank: str, weight: float = 0.5) -> Reranker:
    """Resolve the ``retrieve.rerank`` config value to a reranker.
    ``off``/empty → identity; ``lexical`` → :class:`LexicalReranker`."""
    ref = (rerank or "off").strip()
    if ref in ("", "off"):
        return NoopReranker()
    if ref == "lexical":
        return LexicalReranker(weight)
    raise ValueError(f"unknown reranker {ref!r}; use 'off' or 'lexical'")
