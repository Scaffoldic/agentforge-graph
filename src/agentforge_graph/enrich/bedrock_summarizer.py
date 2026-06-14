"""``BedrockClaudeSummarizer`` — module summaries on AWS Bedrock (feat-012).

Thin endpoint adapter: the summary prompts + plain-text completion live in the
provider-neutral ``ClaudeSummarizer`` (``claude.py``); this wires it to a Bedrock
transport (``BedrockClient``). The Anthropic-API sibling is
``AnthropicClaudeSummarizer`` (``anthropic.py``). Tests use ``ScriptedSummarizer``.
"""

from __future__ import annotations

from .bedrock_client import BedrockClient
from .claude import ClaudeSummarizer


class BedrockClaudeSummarizer(ClaudeSummarizer):
    def __init__(
        self,
        model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-east-1",
        assume_role_arn: str | None = None,
        max_tokens: int = 400,
    ) -> None:
        super().__init__(BedrockClient(model, region, assume_role_arn, max_tokens), model)
