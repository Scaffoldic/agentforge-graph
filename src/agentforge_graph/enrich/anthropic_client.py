"""Shared **direct Anthropic API** Claude client for the enrichers (ENH-003
phase 2 — the non-AWS path).

Mirrors ``BedrockClient``: one lazily-built ``anthropic.Anthropic`` client, a
synchronous Messages call run on a worker thread, cost accumulated from token
usage. Returns ``resp.model_dump()`` — the same ``content``/``usage`` dict shape
Bedrock returns — so ``ClaudeJudge`` / ``ClaudeSummarizer`` parse it unchanged.

The ``anthropic`` SDK ships with the base install (pulled by
``agentforge-anthropic[anthropic]``); it is imported lazily so the
scripted/offline path never needs it. Credentials come from ``ANTHROPIC_API_KEY``
(the SDK's default env var) unless overridden.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from .bedrock_client import price_for  # provider-neutral USD-per-token table

# Bedrock ids carry an inference-profile prefix (``us.``/``eu.``/…) and a
# ``-v1:0`` suffix; the direct API wants the bare model id. Normalising lets the
# same ``enrich.model`` default work on either provider.
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "us-gov.")


def api_model_id(model: str) -> str:
    """Map a Bedrock model id to its Anthropic-API equivalent (idempotent on an
    id that is already an API id). ``us.anthropic.claude-haiku-4-5-20251001-v1:0``
    → ``claude-haiku-4-5-20251001``."""
    m = model
    for prefix in _PROFILE_PREFIXES:
        if m.startswith(prefix):
            m = m[len(prefix) :]
            break
    if m.startswith("anthropic."):
        m = m[len("anthropic.") :]
    if m.endswith("-v1:0"):
        m = m[: -len("-v1:0")]
    return m


class AnthropicClient:
    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "",
        max_tokens: int = 512,
    ) -> None:
        self.model = api_model_id(model)
        self.api_key_env = api_key_env
        self.base_url = base_url
        self.max_tokens = max_tokens
        self._client: Any = None
        self.cost_usd = 0.0

    def _anthropic(self) -> Any:
        if self._client is None:
            import anthropic

            kwargs: dict[str, Any] = {}
            key = os.environ.get(self.api_key_env)
            if key:
                kwargs["api_key"] = key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.Anthropic(**kwargs)
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
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if tools is not None:
            kwargs["tools"] = tools
            if tool_name is not None:
                kwargs["tool_choice"] = {"type": "tool", "name": tool_name}
        resp = self._anthropic().messages.create(**kwargs)
        result: dict[str, Any] = resp.model_dump()
        return result
