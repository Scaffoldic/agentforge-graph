"""Resolve enrichment models (pattern judge + summarizer) from ``EnrichConfig``
via the provider registry.

A single ``enrich.provider`` name selects both roles. Built-ins (``bedrock``,
``anthropic``, ``scripted``) are registered below; third-party providers register
out-of-tree under the ``agentforge_graph.judge_providers`` /
``…summarizer_providers`` entry-point groups (``pip install`` + one
``enrich.provider`` line, no core change). ``bedrock`` (boto3) and ``anthropic``
(the anthropic SDK) are imported lazily so the scripted/offline path needs
neither. ``anthropic`` is the direct Anthropic-API path for non-AWS users
(ENH-003 phase 2). ``scripted`` is the deterministic, credential-free provider
for CI and local runs without a model.
"""

from __future__ import annotations

from collections.abc import Callable

from agentforge_graph.config import EnrichConfig
from agentforge_graph.providers import resolve_provider

from .governs import GovernsMatcher
from .judge import PatternJudge
from .summarizer import Summarizer

JUDGE_GROUP = "agentforge_graph.judge_providers"
SUMMARIZER_GROUP = "agentforge_graph.summarizer_providers"
GOVERNS_GROUP = "agentforge_graph.governs_matcher_providers"

JudgeBuilder = Callable[[EnrichConfig], PatternJudge]
SummarizerBuilder = Callable[[EnrichConfig], Summarizer]
GovernsMatcherBuilder = Callable[[EnrichConfig], GovernsMatcher]


def _build_scripted_judge(cfg: EnrichConfig) -> PatternJudge:
    from .judge import ScriptedJudge

    return ScriptedJudge()


def _build_bedrock_judge(cfg: EnrichConfig) -> PatternJudge:
    from .bedrock import BedrockClaudeJudge  # lazy: only needs boto3 on this path

    return BedrockClaudeJudge(cfg.model, cfg.region, cfg.assume_role_arn or None)


def _build_anthropic_judge(cfg: EnrichConfig) -> PatternJudge:
    from .anthropic import AnthropicClaudeJudge  # lazy: only needs the anthropic SDK here

    return AnthropicClaudeJudge(
        cfg.model, api_key_env=cfg.api_key_env or "ANTHROPIC_API_KEY", base_url=cfg.base_url
    )


def _build_scripted_summarizer(cfg: EnrichConfig) -> Summarizer:
    from .summarizer import ScriptedSummarizer

    return ScriptedSummarizer()


def _build_bedrock_summarizer(cfg: EnrichConfig) -> Summarizer:
    from .bedrock_summarizer import BedrockClaudeSummarizer  # lazy: boto3 on this path

    return BedrockClaudeSummarizer(cfg.model, cfg.region, cfg.assume_role_arn or None)


def _build_anthropic_summarizer(cfg: EnrichConfig) -> Summarizer:
    from .anthropic import AnthropicClaudeSummarizer  # lazy: anthropic SDK on this path

    return AnthropicClaudeSummarizer(
        cfg.model, api_key_env=cfg.api_key_env or "ANTHROPIC_API_KEY", base_url=cfg.base_url
    )


def _build_scripted_governs_matcher(cfg: EnrichConfig) -> GovernsMatcher:
    from .governs import ScriptedMatcher

    return ScriptedMatcher()


def _build_bedrock_governs_matcher(cfg: EnrichConfig) -> GovernsMatcher:
    from .bedrock_client import BedrockClient  # lazy: boto3 only on this path
    from .governs import ClaudeGovernsMatcher

    client = BedrockClient(cfg.model, cfg.region, cfg.assume_role_arn or None)
    return ClaudeGovernsMatcher(client, cfg.model)


def _build_anthropic_governs_matcher(cfg: EnrichConfig) -> GovernsMatcher:
    from .anthropic_client import AnthropicClient  # lazy: anthropic SDK only here
    from .governs import ClaudeGovernsMatcher

    client = AnthropicClient(cfg.model, cfg.api_key_env or "ANTHROPIC_API_KEY", cfg.base_url)
    return ClaudeGovernsMatcher(client, client.model)


_JUDGE_BUILTINS: dict[str, JudgeBuilder] = {
    "bedrock": _build_bedrock_judge,
    "anthropic": _build_anthropic_judge,
    "scripted": _build_scripted_judge,
}
_SUMMARIZER_BUILTINS: dict[str, SummarizerBuilder] = {
    "bedrock": _build_bedrock_summarizer,
    "anthropic": _build_anthropic_summarizer,
    "scripted": _build_scripted_summarizer,
}
_GOVERNS_BUILTINS: dict[str, GovernsMatcherBuilder] = {
    "bedrock": _build_bedrock_governs_matcher,
    "anthropic": _build_anthropic_governs_matcher,
    "scripted": _build_scripted_governs_matcher,
}


def judge_from_config(cfg: EnrichConfig) -> PatternJudge:
    """Construct the ``PatternJudge`` selected by ``cfg.provider`` via the registry."""
    builder = resolve_provider(cfg.provider, _JUDGE_BUILTINS, JUDGE_GROUP, role="judge")
    return builder(cfg)


def summarizer_from_config(cfg: EnrichConfig) -> Summarizer:
    """Construct the ``Summarizer`` selected by ``cfg.provider`` via the registry."""
    builder = resolve_provider(
        cfg.provider, _SUMMARIZER_BUILTINS, SUMMARIZER_GROUP, role="summarizer"
    )
    return builder(cfg)


def governs_matcher_from_config(cfg: EnrichConfig) -> GovernsMatcher:
    """Construct the ``GovernsMatcher`` selected by ``cfg.provider`` (feat-010)."""
    builder = resolve_provider(
        cfg.provider, _GOVERNS_BUILTINS, GOVERNS_GROUP, role="governs_matcher"
    )
    return builder(cfg)
