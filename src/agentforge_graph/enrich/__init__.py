"""LLM enrichment (feat-012): turn the code graph into a knowledge graph.

MVP: **design-pattern tagging** — deterministic structural heuristics nominate
candidates, a budgeted LLM judge confirms them, and confirmed verdicts become
``TAGGED`` edges to a fixed v1 ``PatternTag`` taxonomy with honest ``llm``
provenance + confidence + rationale. The judge is injectable
(``ScriptedJudge`` for tests, ``BedrockClaudeJudge`` live), so all orchestration
is deterministic. This is the framework layer (ADR-0001: ``enrich`` may import
``agentforge``); never runs implicitly (``ckg enrich`` only).
"""

from __future__ import annotations

from .enricher import PatternTagEnricher
from .governs import (
    ClaudeGovernsMatcher,
    GovernsCandidate,
    GovernsMatch,
    GovernsMatcher,
    ScriptedMatcher,
)
from .governs_enricher import DecisionGovernsInferencer
from .heuristics import Candidate, PatternHeuristics
from .judge import PatternJudge, ScriptedJudge, Verdict
from .registry import (
    JUDGE_GROUP,
    SUMMARIZER_GROUP,
    governs_matcher_from_config,
    judge_from_config,
    summarizer_from_config,
)
from .report import EnrichReport, GovernsReport, SummaryInfo, SummaryReport, TaggedInfo
from .summarizer import FileContext, ScriptedSummarizer, Summarizer, Summary
from .summary_enricher import SummaryEnricher, repo_node_id, summary_id
from .taxonomy import TAXONOMY_V1, is_pattern, pattern_tag_id

__all__ = [
    "PatternTagEnricher",
    "PatternHeuristics",
    "Candidate",
    "PatternJudge",
    "ScriptedJudge",
    "Verdict",
    "judge_from_config",
    "summarizer_from_config",
    "governs_matcher_from_config",
    "DecisionGovernsInferencer",
    "GovernsMatcher",
    "ScriptedMatcher",
    "ClaudeGovernsMatcher",
    "GovernsCandidate",
    "GovernsMatch",
    "GovernsReport",
    "JUDGE_GROUP",
    "SUMMARIZER_GROUP",
    "EnrichReport",
    "TaggedInfo",
    "SummaryReport",
    "SummaryInfo",
    "SummaryEnricher",
    "Summarizer",
    "ScriptedSummarizer",
    "Summary",
    "FileContext",
    "summary_id",
    "repo_node_id",
    "TAXONOMY_V1",
    "is_pattern",
    "pattern_tag_id",
]
