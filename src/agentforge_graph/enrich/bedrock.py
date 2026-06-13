"""``BedrockClaudeJudge`` — the live pattern judge on AWS Bedrock (feat-012).

Anthropic Claude via Bedrock (same credential path as the Cohere embedder):
boto3 lazy-imported, optional STS assume-role, sync call on a worker thread.
A forced tool call returns a structured verdict per nominated pattern; cost is
computed from token usage. This is the only model-calling class — everything
else (heuristics, orchestration, budget) is exercised with the ``ScriptedJudge``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from .heuristics import Candidate
from .judge import Verdict

# USD per 1M tokens (input, output). Conservative defaults; cheap tier.
_PRICES: dict[str, tuple[float, float]] = {
    "haiku-4-5": (1.0, 5.0),
    "haiku": (0.80, 4.0),
    "sonnet": (3.0, 15.0),
}
_DEFAULT_PRICE = (1.0, 5.0)

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


def _price_for(model: str) -> tuple[float, float]:
    for key, price in _PRICES.items():
        if key in model:
            return price
    return _DEFAULT_PRICE


class BedrockClaudeJudge:
    def __init__(
        self,
        model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-east-1",
        assume_role_arn: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        self.model = model
        self.region = region
        self.assume_role_arn = assume_role_arn
        self.max_tokens = max_tokens
        self._client: Any = None
        self._cost = 0.0

    def _bedrock(self) -> Any:
        if self._client is None:
            import boto3

            if self.assume_role_arn:
                sts = boto3.client("sts", region_name=self.region)
                creds = sts.assume_role(RoleArn=self.assume_role_arn, RoleSessionName="ckg-enrich")[
                    "Credentials"
                ]
                self._client = boto3.client(
                    "bedrock-runtime",
                    region_name=self.region,
                    aws_access_key_id=creds["AccessKeyId"],
                    aws_secret_access_key=creds["SecretAccessKey"],
                    aws_session_token=creds["SessionToken"],
                )
            else:
                self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    async def judge(self, candidate: Candidate) -> list[Verdict]:
        if not candidate.patterns:
            return []
        resp = await asyncio.to_thread(self._invoke, candidate)
        verdicts, usage = self._parse(resp)
        cents_in, cents_out = _price_for(self.model)
        self._cost += (
            usage.get("input_tokens", 0) * cents_in + usage.get("output_tokens", 0) * cents_out
        ) / 1_000_000
        nominated = set(candidate.patterns)
        return [v for v in verdicts if v.pattern in nominated]

    @property
    def cost_usd(self) -> float:
        return self._cost

    def _prompt(self, c: Candidate) -> str:
        methods = "\n".join(f"  - {n}: {sig}" for n, sig in c.methods[:30]) or "  (none)"
        return (
            f"{c.kind} `{c.name}`\nsignature: {c.signature}\nmethods:\n{methods}\n\n"
            f"candidate patterns (from structural heuristics): {', '.join(c.patterns)}\n"
            f"evidence: {'; '.join(c.evidence)}\n\n"
            "Return a verdict for EACH candidate pattern."
        )

    def _invoke(self, c: Candidate) -> dict[str, Any]:
        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": self.max_tokens,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": self._prompt(c)}],
                "tools": [_TOOL],
                "tool_choice": {"type": "tool", "name": "submit_verdicts"},
            }
        )
        resp = self._bedrock().invoke_model(
            modelId=self.model, contentType="application/json", accept="application/json", body=body
        )
        payload: dict[str, Any] = json.loads(resp["body"].read())
        return payload

    @staticmethod
    def _parse(payload: dict[str, Any]) -> tuple[list[Verdict], dict[str, int]]:
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
        return verdicts, payload.get("usage", {})
