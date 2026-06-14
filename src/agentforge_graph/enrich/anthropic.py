"""``AnthropicClaudeJudge`` / ``AnthropicClaudeSummarizer`` — the **direct
Anthropic API** enrichers (ENH-003 phase 2; the non-AWS Claude path).

Thin endpoint adapters: the judging/summary logic is the provider-neutral
``ClaudeJudge`` / ``ClaudeSummarizer`` (``claude.py``); these wire it to an
``AnthropicClient`` transport. Pick them with ``enrich.provider: anthropic`` and
set ``ANTHROPIC_API_KEY`` (``enrich.model`` may stay the Bedrock default — the
id is normalised to its API form). Tests use the ``Scripted*`` variants.
"""

from __future__ import annotations

from .anthropic_client import AnthropicClient
from .claude import ClaudeJudge, ClaudeSummarizer


class AnthropicClaudeJudge(ClaudeJudge):
    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "",
        max_tokens: int = 512,
    ) -> None:
        client = AnthropicClient(model, api_key_env, base_url, max_tokens)
        super().__init__(client, client.model)


class AnthropicClaudeSummarizer(ClaudeSummarizer):
    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        api_key_env: str = "ANTHROPIC_API_KEY",
        base_url: str = "",
        max_tokens: int = 400,
    ) -> None:
        client = AnthropicClient(model, api_key_env, base_url, max_tokens)
        super().__init__(client, client.model)
