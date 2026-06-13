"""The pattern judge interface (feat-012) — stage 2.

A ``PatternJudge`` confirms or rejects a stage-1 ``Candidate``'s nominated
patterns, returning a ``Verdict`` per pattern with confidence + rationale. The
interface is injectable (the Embedder/FakeEmbedder pattern): the live
``BedrockClaudeJudge`` (``bedrock.py``) is the only model-calling class, while
``ScriptedJudge`` keeps the whole enricher deterministic and testable.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .heuristics import Candidate


class Verdict(BaseModel):
    pattern: str
    is_match: bool
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


@runtime_checkable
class PatternJudge(Protocol):
    async def judge(self, candidate: Candidate) -> list[Verdict]: ...

    @property
    def cost_usd(self) -> float:
        """Cumulative USD spent so far (0 for the scripted judge)."""
        ...


ScriptFn = Callable[[Candidate], list[Verdict]]


class ScriptedJudge:
    """Deterministic judge for tests. Drive it with a function, or with the
    default that confirms every nominated pattern at a fixed confidence. An
    optional ``per_call_usd`` lets a test exercise the budget breaker."""

    def __init__(self, fn: ScriptFn | None = None, per_call_usd: float = 0.0) -> None:
        self._fn = fn or self._confirm_all
        self._per_call_usd = per_call_usd
        self._cost = 0.0

    @staticmethod
    def _confirm_all(candidate: Candidate) -> list[Verdict]:
        return [
            Verdict(pattern=p, is_match=True, confidence=0.9, rationale="scripted")
            for p in candidate.patterns
        ]

    async def judge(self, candidate: Candidate) -> list[Verdict]:
        self._cost += self._per_call_usd
        return self._fn(candidate)

    @property
    def cost_usd(self) -> float:
        return self._cost
