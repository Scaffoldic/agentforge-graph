"""Token budgeting for the chunker.

A fast, model-independent heuristic — exactness doesn't matter, only that
budgeting and the boundary tests use the *same* estimate. A real tokenizer
is a drop-in replacement behind this function (ADR-0007 risk note).
"""

from __future__ import annotations


def estimate_tokens(text: str) -> int:
    """Approximate token count: ~4 chars/token, floored to the word count."""
    if not text.strip():
        return 0
    return max(len(text) // 4, len(text.split()), 1)
