"""Provider-neutral Claude pattern judge + summarizer (ENH-003 phase 2).

The judge/summarizer logic is identical whether Claude runs on **AWS Bedrock**
or the **direct Anthropic API**: both return the Anthropic *Messages* response
shape (``content`` blocks + ``usage``). Only the transport *client* differs. So
the prompts + parsing live here once, and the per-endpoint modules
(``bedrock.py``, ``anthropic.py``) just supply a ``ClaudeClient``.

Tests drive the deterministic ``ScriptedJudge`` / ``ScriptedSummarizer`` instead;
this base is exercised with a stub client (no network) plus the env-gated live
tests.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

# ``price_for`` / ``text_of`` are provider-neutral helpers that have lived in
# ``bedrock_client`` since feat-012; import them here rather than move the file
# (keeps the public import path stable for existing tests).
from .bedrock_client import text_of
from .heuristics import Candidate
from .judge import Verdict
from .summarizer import FileContext, Summary

_JUDGE_SYSTEM = (
    "You classify a code symbol against GoF and architectural design patterns. "
    "Confirm a pattern ONLY when the symbol's structure clearly supports it; prefer "
    "rejecting over guessing. For each candidate pattern give is_match, a confidence "
    "in [0,1], and a one-sentence rationale that cites the structural evidence."
)

_VERDICT_TOOL = {
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


@runtime_checkable
class ClaudeClient(Protocol):
    """One Messages call + cumulative cost. ``BedrockClient`` and
    ``AnthropicClient`` both satisfy this."""

    cost_usd: float

    async def invoke(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]] | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the raw Messages payload (``content`` blocks + ``usage``)."""
        ...


class ClaudeJudge:
    """Pattern judge over any ``ClaudeClient``. A forced ``submit_verdicts`` tool
    call yields one structured verdict per nominated pattern."""

    def __init__(self, client: ClaudeClient, model: str) -> None:
        self.model = model
        self._client = client

    async def judge(self, candidate: Candidate) -> list[Verdict]:
        if not candidate.patterns:
            return []
        payload = await self._client.invoke(
            _JUDGE_SYSTEM,
            self._prompt(candidate),
            tools=[_VERDICT_TOOL],
            tool_name="submit_verdicts",
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


class ClaudeSummarizer:
    """Module/repo summaries over any ``ClaudeClient`` — plain-text completions."""

    def __init__(self, client: ClaudeClient, model: str) -> None:
        self.model = model
        self._client = client

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
