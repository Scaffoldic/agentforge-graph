"""``BedrockClaudeJudge`` — the pattern judge on AWS Bedrock (feat-012).

Thin endpoint adapter: the judging logic (prompts, forced ``submit_verdicts``
tool call, verdict parsing, cost) lives in the provider-neutral ``ClaudeJudge``
(``claude.py``); this just wires it to a Bedrock transport (``BedrockClient``).
The Anthropic-API sibling is ``AnthropicClaudeJudge`` (``anthropic.py``). Tests
use the ``ScriptedJudge`` instead.
"""

from __future__ import annotations

from .bedrock_client import BedrockClient
from .claude import ClaudeJudge


class BedrockClaudeJudge(ClaudeJudge):
    def __init__(
        self,
        model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-east-1",
        assume_role_arn: str | None = None,
        max_tokens: int = 512,
    ) -> None:
        super().__init__(BedrockClient(model, region, assume_role_arn, max_tokens), model)
