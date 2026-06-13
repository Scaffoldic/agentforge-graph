"""Shared AWS Bedrock Claude client for the enrichers (feat-012).

One boto3 ``bedrock-runtime`` client (lazy, optional STS assume-role, sync on a
worker thread), one ``invoke`` that runs the Anthropic Messages API on Bedrock
and accumulates cost from token usage. The pattern judge and the summarizer both
ride this; it is the only model-calling surface (deterministic tests use the
scripted variants).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

# USD per 1M tokens (input, output). Conservative defaults; cheap tier.
_PRICES: dict[str, tuple[float, float]] = {
    "haiku-4-5": (1.0, 5.0),
    "haiku": (0.80, 4.0),
    "sonnet": (3.0, 15.0),
}
_DEFAULT_PRICE = (1.0, 5.0)


def price_for(model: str) -> tuple[float, float]:
    for key, price in _PRICES.items():
        if key in model:
            return price
    return _DEFAULT_PRICE


class BedrockClient:
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
        self.cost_usd = 0.0

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

    async def invoke(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]] | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        """One Messages call; accumulates cost from usage. Returns the raw
        payload (``content`` blocks + ``usage``)."""
        payload = await asyncio.to_thread(self._invoke, system, user, tools, tool_name)
        cents_in, cents_out = price_for(self.model)
        usage = payload.get("usage", {})
        self.cost_usd += (
            usage.get("input_tokens", 0) * cents_in + usage.get("output_tokens", 0) * cents_out
        ) / 1_000_000
        return payload

    def _invoke(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]] | None,
        tool_name: str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if tools is not None:
            body["tools"] = tools
            if tool_name is not None:
                body["tool_choice"] = {"type": "tool", "name": tool_name}
        resp = self._bedrock().invoke_model(
            modelId=self.model,
            contentType="application/json",
            accept="application/json",
            body=json.dumps(body),
        )
        result: dict[str, Any] = json.loads(resp["body"].read())
        return result


def text_of(payload: dict[str, Any]) -> str:
    """Concatenate the text blocks of a Messages response."""
    return "".join(
        b.get("text", "") for b in payload.get("content", []) if b.get("type") == "text"
    ).strip()
