"""``BedrockClaudeSummarizer`` — live module summaries on AWS Bedrock (feat-012).

Plain-text Claude completion per file (and once for the repo), riding the shared
``BedrockClient`` for credentials + cost. Prompts insist the model summarize
only what the signatures show — honesty is the ``llm`` provenance + model.
"""

from __future__ import annotations

from .bedrock_client import BedrockClient, text_of
from .summarizer import FileContext, Summary

_FILE_SYSTEM = (
    "You write a one-paragraph summary of a source file for a developer orienting "
    "in the codebase. State what the file is FOR and the role of its main symbols. "
    "Summarize only what the signatures and names show — do not invent behaviour. "
    "No preamble, no bullet lists."
)
_REPO_SYSTEM = (
    "You write a one-paragraph summary of a codebase from its per-file summaries. "
    "State what the system does and how the major pieces fit. No preamble."
)


class BedrockClaudeSummarizer:
    def __init__(
        self,
        model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        region: str = "us-east-1",
        assume_role_arn: str | None = None,
        max_tokens: int = 400,
    ) -> None:
        self.model = model
        self._client = BedrockClient(model, region, assume_role_arn, max_tokens)

    async def summarize_file(self, ctx: FileContext, max_words: int) -> Summary:
        symbols = "\n".join(f"  - {n}: {sig}" for n, sig in ctx.symbols[:60]) or "  (no symbols)"
        imports = ", ".join(ctx.imports[:20]) or "(none)"
        user = (
            f"File: {ctx.path}\nImports: {imports}\nSymbols:\n{symbols}\n\n"
            f"Summarize this file in at most {max_words} words."
        )
        payload = await self._client.invoke(_FILE_SYSTEM, user)
        return Summary(text=text_of(payload), model=self.model)

    async def summarize_repo(
        self, repo: str, file_summaries: list[tuple[str, str]], max_words: int
    ) -> Summary:
        joined = "\n".join(f"- {path}: {text}" for path, text in file_summaries[:200])
        user = (
            f"Repository: {repo}\nPer-file summaries:\n{joined}\n\n"
            f"Summarize the whole codebase in at most {max_words} words."
        )
        payload = await self._client.invoke(_REPO_SYSTEM, user)
        return Summary(text=text_of(payload), model=self.model)

    @property
    def cost_usd(self) -> float:
        return self._client.cost_usd
