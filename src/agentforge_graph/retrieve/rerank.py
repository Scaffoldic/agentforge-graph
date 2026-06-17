"""Reranking hook (feat-006 seam; ENH-009).

Three modes, all behind ``retrieve.rerank``:

- ``off`` (default) — identity; pure cosine + graph score.
- ``lexical`` — a deterministic, dependency-free blend of the base score with the
  **subtoken overlap** between the query and the candidate's name + code, so a
  chunk whose symbol the query names (``ZodObject``, ``_parse``, ``res.send``)
  sorts up even when its raw cosine landed *near* the answer. Useful for
  keyword/symbol-naming queries; measured mixed on prose (hence opt-in).
- ``cross_encoder`` — a real semantic re-score: a cross-encoder relevance model
  (``sentence-transformers``, the ``rerank`` extra) scores each (query,
  candidate) pair, blended with the base score. The highest-leverage lever for
  natural-language → symbol precision. The model is lazy-loaded so the base
  install / CI never import torch; the blend logic is injectable (``CrossScorer``)
  so it is tested without the model. Third-party only — no ``agentforge`` import
  (ADR-0001).

All rerankers are deterministic given their inputs and order-stable on ties."""

from __future__ import annotations

import asyncio
import math
import re
from typing import Protocol

from .pack import ContextItem

# A capable, small default cross-encoder; overridable via ``retrieve.rerank_model``.
DEFAULT_CROSS_ENCODER = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_MAX_CANDIDATE_CHARS = 2000  # cross-encoders truncate anyway; bound the payload

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


class CrossScorer(Protocol):
    """Scores (query, candidate-text) pairs — higher = more relevant. The
    injection seam that keeps the model out of the blend logic (and out of CI)."""

    def score(self, query: str, texts: list[str]) -> list[float]: ...


def _candidate_text(it: ContextItem) -> str:
    body = it.code or it.signature()
    return f"{it.name}\n{body}"[:_MAX_CANDIDATE_CHARS]


class CrossEncoderReranker:
    """Re-score the top-k candidates with a cross-encoder, then blend and re-sort.

    ``final = (1 - weight)·base + weight·σ(cross_score)`` — the cross-encoder's
    raw relevance logit is squashed to ``[0, 1]`` (so it is comparable to the
    cosine-scale base score) and blended. The model call runs off the event loop
    (``to_thread``); identity on an empty query/candidate set."""

    def __init__(self, scorer: CrossScorer, weight: float = 0.5) -> None:
        self._scorer = scorer
        self._w = max(0.0, min(1.0, weight))

    async def rerank(self, query: str, items: list[ContextItem]) -> list[ContextItem]:
        if not query or not items:
            return items
        texts = [_candidate_text(it) for it in items]
        raw = await asyncio.to_thread(self._scorer.score, query, texts)
        rescored: list[ContextItem] = []
        for it, r in zip(items, raw, strict=True):
            ce = 1.0 / (1.0 + math.exp(-r))  # σ → [0, 1]
            final = (1.0 - self._w) * it.score + self._w * ce
            rescored.append(
                it.model_copy(update={"score": final, "why": [*it.why, f"cross-encoder {ce:.2f}"]})
            )
        rescored.sort(key=lambda i: (-i.score, i.id))
        return rescored


class SentenceTransformerScorer:
    """A ``CrossScorer`` backed by ``sentence_transformers.CrossEncoder``. The
    model is loaded lazily on first use, so importing this module (and running
    CI) never pulls torch; the import error names the extra to install."""

    def __init__(self, model_name: str = DEFAULT_CROSS_ENCODER) -> None:
        self._model_name = model_name
        self._model: object | None = None

    def _ensure_model(self) -> object:
        if self._model is None:
            try:
                from sentence_transformers import CrossEncoder
            except ImportError as exc:  # the extra isn't installed
                raise ImportError(
                    "cross-encoder rerank needs the 'rerank' extra (uv sync --extra rerank)"
                ) from exc
            self._model = CrossEncoder(self._model_name)
        return self._model

    def score(self, query: str, texts: list[str]) -> list[float]:
        if not texts:
            return []
        model = self._ensure_model()
        return [float(s) for s in model.predict([(query, t) for t in texts])]  # type: ignore[attr-defined]


def reranker_from_config(rerank: str, weight: float = 0.5, model: str = "") -> Reranker:
    """Resolve the ``retrieve.rerank`` config value to a reranker.
    ``off``/empty → identity; ``lexical`` → :class:`LexicalReranker`;
    ``cross_encoder`` → :class:`CrossEncoderReranker` over a lazily-loaded
    sentence-transformers model (``model`` overrides the default)."""
    ref = (rerank or "off").strip()
    if ref in ("", "off"):
        return NoopReranker()
    if ref == "lexical":
        return LexicalReranker(weight)
    if ref == "cross_encoder":
        return CrossEncoderReranker(
            SentenceTransformerScorer(model or DEFAULT_CROSS_ENCODER), weight
        )
    raise ValueError(f"unknown reranker {ref!r}; use 'off', 'lexical' or 'cross_encoder'")
