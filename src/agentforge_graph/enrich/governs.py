"""The ``infer_governs`` LLM matcher (feat-010 follow-up).

When an ADR's prose does not name the code it governs by path/symbol, the
deterministic mention parser produces zero ``GOVERNS`` edges. This optional pass
asks a model to match a decision's text against the repo's candidate symbols and
proposes ``GOVERNS`` edges with honest ``llm`` provenance + confidence.

The matcher is injectable (the Embedder/PatternJudge pattern): the live
``ClaudeGovernsMatcher`` runs over any ``ClaudeClient`` (Bedrock or the Anthropic
API); the ``ScriptedMatcher`` keeps the enricher deterministic and credential-free
for tests. This is a framework-layer module (ADR-0001: ``enrich`` may import
``agentforge``); the deterministic ``knowledge`` package stays model-free.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .claude import ClaudeClient


class GovernsCandidate(BaseModel):
    """A symbol a decision might govern — what the matcher sees per candidate."""

    symbol_id: str
    name: str
    kind: str
    signature: str = ""
    path: str = ""


class GovernsMatch(BaseModel):
    """A proposed ``GOVERNS`` link from a decision to one candidate symbol."""

    symbol_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str = ""


@runtime_checkable
class GovernsMatcher(Protocol):
    async def match(
        self, title: str, text: str, candidates: list[GovernsCandidate]
    ) -> list[GovernsMatch]: ...

    @property
    def cost_usd(self) -> float:
        """Cumulative USD spent so far (0 for the scripted matcher)."""
        ...


ScriptFn = Callable[[str, str, list[GovernsCandidate]], list[GovernsMatch]]


class ScriptedMatcher:
    """Deterministic matcher for tests. Drive it with a function; the default
    matches nothing. An optional ``per_call_usd`` exercises the budget breaker."""

    def __init__(self, fn: ScriptFn | None = None, per_call_usd: float = 0.0) -> None:
        self._fn = fn or (lambda title, text, cands: [])
        self._per_call_usd = per_call_usd
        self._cost = 0.0

    async def match(
        self, title: str, text: str, candidates: list[GovernsCandidate]
    ) -> list[GovernsMatch]:
        self._cost += self._per_call_usd
        return self._fn(title, text, candidates)

    @property
    def cost_usd(self) -> float:
        return self._cost


_GOVERNS_SYSTEM = (
    "You match an architecture decision record (ADR) to the code symbols it governs. "
    "A symbol is governed when the decision's rules plainly constrain how that symbol "
    "is designed, implemented, or changed. Be conservative: propose a match ONLY when "
    "the decision clearly applies to the symbol — prefer proposing nothing over "
    "guessing. For each match give a confidence in [0,1] and a one-sentence rationale "
    "citing the decision text."
)

_GOVERNS_TOOL = {
    "name": "submit_governs",
    "description": "Return the candidate symbols this decision governs (possibly none).",
    "input_schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "symbol_index": {"type": "integer"},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["symbol_index", "confidence", "rationale"],
                },
            }
        },
        "required": ["matches"],
    },
}


class ClaudeGovernsMatcher:
    """``infer_governs`` matcher over any ``ClaudeClient``. A forced
    ``submit_governs`` tool call returns candidate indices + confidences."""

    def __init__(self, client: ClaudeClient, model: str) -> None:
        self.model = model
        self._client = client

    async def match(
        self, title: str, text: str, candidates: list[GovernsCandidate]
    ) -> list[GovernsMatch]:
        if not candidates:
            return []
        payload = await self._client.invoke(
            _GOVERNS_SYSTEM,
            self._prompt(title, text, candidates),
            tools=[_GOVERNS_TOOL],
            tool_name="submit_governs",
        )
        return self._parse(payload, candidates)

    @property
    def cost_usd(self) -> float:
        return self._client.cost_usd

    @staticmethod
    def _prompt(title: str, text: str, candidates: list[GovernsCandidate]) -> str:
        listing = "\n".join(
            f"  [{i}] {c.kind} `{c.name}` — {c.path}"
            + (f" :: {c.signature}" if c.signature else "")
            for i, c in enumerate(candidates)
        )
        return (
            f"Decision: {title}\n\n{text.strip()}\n\n"
            f"Candidate symbols (index in brackets):\n{listing}\n\n"
            "Return the candidates this decision governs by their index. "
            "If none clearly apply, return an empty list."
        )

    @staticmethod
    def _parse(payload: dict[str, Any], candidates: list[GovernsCandidate]) -> list[GovernsMatch]:
        matches: list[GovernsMatch] = []
        seen: set[int] = set()
        for block in payload.get("content", []):
            if block.get("type") != "tool_use":
                continue
            for raw in block.get("input", {}).get("matches", []):
                try:
                    idx = int(raw.get("symbol_index", -1))
                except (TypeError, ValueError):
                    continue
                if idx < 0 or idx >= len(candidates) or idx in seen:
                    continue
                seen.add(idx)
                conf = max(0.0, min(1.0, float(raw.get("confidence", 0.0) or 0.0)))
                matches.append(
                    GovernsMatch(
                        symbol_id=candidates[idx].symbol_id,
                        confidence=conf,
                        rationale=str(raw.get("rationale", "")),
                    )
                )
        return matches
