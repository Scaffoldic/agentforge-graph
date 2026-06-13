"""Resolve enrichment models (pattern judge + summarizer) from ``EnrichConfig``
via the provider registry.

A single ``enrich.provider`` name selects both roles. Built-ins (``bedrock``,
``scripted``) are registered below; third-party providers register out-of-tree
under the ``agentforge_graph.judge_providers`` / ``…summarizer_providers``
entry-point groups (``pip install`` + one ``enrich.provider`` line, no core
change). Bedrock is imported lazily so the scripted/offline path never needs
boto3. ``scripted`` is the deterministic, credential-free provider for CI and
local runs without a model.
"""

from __future__ import annotations

from collections.abc import Callable

from agentforge_graph.config import EnrichConfig
from agentforge_graph.providers import resolve_provider

from .judge import PatternJudge
from .summarizer import Summarizer

JUDGE_GROUP = "agentforge_graph.judge_providers"
SUMMARIZER_GROUP = "agentforge_graph.summarizer_providers"

JudgeBuilder = Callable[[EnrichConfig], PatternJudge]
SummarizerBuilder = Callable[[EnrichConfig], Summarizer]


def _build_scripted_judge(cfg: EnrichConfig) -> PatternJudge:
    from .judge import ScriptedJudge

    return ScriptedJudge()


def _build_bedrock_judge(cfg: EnrichConfig) -> PatternJudge:
    from .bedrock import BedrockClaudeJudge  # lazy: only needs boto3 on this path

    return BedrockClaudeJudge(cfg.model, cfg.region, cfg.assume_role_arn or None)


def _build_scripted_summarizer(cfg: EnrichConfig) -> Summarizer:
    from .summarizer import ScriptedSummarizer

    return ScriptedSummarizer()


def _build_bedrock_summarizer(cfg: EnrichConfig) -> Summarizer:
    from .bedrock_summarizer import BedrockClaudeSummarizer  # lazy: boto3 on this path

    return BedrockClaudeSummarizer(cfg.model, cfg.region, cfg.assume_role_arn or None)


_JUDGE_BUILTINS: dict[str, JudgeBuilder] = {
    "bedrock": _build_bedrock_judge,
    "scripted": _build_scripted_judge,
}
_SUMMARIZER_BUILTINS: dict[str, SummarizerBuilder] = {
    "bedrock": _build_bedrock_summarizer,
    "scripted": _build_scripted_summarizer,
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
