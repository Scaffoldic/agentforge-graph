"""``BedrockClaudeJudge`` — the live pattern judge on AWS Bedrock (feat-012).

A forced tool call returns a structured verdict per nominated pattern; cost is
tracked by the shared ``BedrockClient``. This is the only model-calling class
for tagging — everything else is exercised with the ``ScriptedJudge``.
"""

from __future__ import annotations

from typing import Any

from .bedrock_client import BedrockClient
from .heuristics import Candidate
from .judge import Verdict

_SYSTEM = (
    "You classify a code symbol against GoF and architectural design patterns. "
    "Confirm a pattern ONLY when the symbol's structure clearly supports it; prefer "
    "rejecting over guessing. For each candidate pattern give is_match, a confidence "
    "in [0,1], and a one-sentence rationale that cites the structural evidence."
)

_TOOL = {
    "name": "submit_verdicts",
    "description": "Return one verdict per candidate pattern.",
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "is_match": {"type": "boolean"},
                        "confidence": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["pattern", "is_match", "confidence", "rationale"],
                },
            }
        },
        "required": ["verdicts"],
    },
}


class BedrockClaudeJudge:
    def __init__(
        self,
        model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-east-1",
        assume_role_arn: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        self.model = model
        self._client = BedrockClient(model, region, assume_role_arn, max_tokens)

    async def judge(self, candidate: Candidate) -> list[Verdict]:
        if not candidate.patterns:
            return []
        payload = await self._client.invoke(
            _SYSTEM, self._prompt(candidate), tools=[_TOOL], tool_name="submit_verdicts"
        )
        nominated = set(candidate.patterns)
        return [v for v in self._parse(payload) if v.pattern in nominated]

    @property
    def cost_usd(self) -> float:
        return self._client.cost_usd

    @staticmethod
    def _prompt(c: Candidate) -> str:
        methods = "\n".join(f"  - {n}: {sig}" for n, sig in c.methods[:30]) or "  (none)"
        return (
            f"{c.kind} `{c.name}`\nsignature: {c.signature}\nmethods:\n{methods}\n\n"
            f"candidate patterns (from structural heuristics): {', '.join(c.patterns)}\n"
            f"evidence: {'; '.join(c.evidence)}\n\n"
            "Return a verdict for EACH candidate pattern."
        )

    @staticmethod
    def _parse(payload: dict[str, Any]) -> list[Verdict]:
        verdicts: list[Verdict] = []
        for block in payload.get("content", []):
            if block.get("type") == "tool_use":
                for raw in block.get("input", {}).get("verdicts", []):
                    try:
                        conf = max(0.0, min(1.0, float(raw.get("confidence", 0.0))))
                        verdicts.append(
                            Verdict(
                                pattern=str(raw.get("pattern", "")),
                                is_match=bool(raw.get("is_match", False)),
                                confidence=conf,
                                rationale=str(raw.get("rationale", "")),
                            )
                        )
                    except (TypeError, ValueError):
                        continue
        return verdicts
