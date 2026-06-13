"""The summarizer interface (feat-012 summaries) — injectable like PatternJudge.

``BedrockClaudeSummarizer`` is the live adapter; ``ScriptedSummarizer`` keeps the
bottom-up enricher (ordering, embedding, budget, idempotency) deterministic in
CI with no model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


@dataclass
class FileContext:
    path: str
    symbols: list[tuple[str, str]] = field(default_factory=list)  # (name, signature)
    imports: list[str] = field(default_factory=list)


class Summary(BaseModel):
    text: str
    model: str = ""


@runtime_checkable
class Summarizer(Protocol):
    async def summarize_file(self, ctx: FileContext, max_words: int) -> Summary: ...

    async def summarize_repo(
        self, repo: str, file_summaries: list[tuple[str, str]], max_words: int
    ) -> Summary: ...

    @property
    def cost_usd(self) -> float: ...


FileFn = Callable[[FileContext], str]


class ScriptedSummarizer:
    """Deterministic summarizer for tests. The default derives a stable string
    from the context; pass ``fn`` to script file summaries."""

    def __init__(self, fn: FileFn | None = None) -> None:
        self._fn = fn or (lambda ctx: f"summary of {ctx.path} ({len(ctx.symbols)} symbols)")
        self._cost = 0.0

    async def summarize_file(self, ctx: FileContext, max_words: int) -> Summary:
        return Summary(text=self._fn(ctx), model="scripted")

    async def summarize_repo(
        self, repo: str, file_summaries: list[tuple[str, str]], max_words: int
    ) -> Summary:
        return Summary(text=f"repo {repo}: {len(file_summaries)} files", model="scripted")

    @property
    def cost_usd(self) -> float:
        return self._cost
