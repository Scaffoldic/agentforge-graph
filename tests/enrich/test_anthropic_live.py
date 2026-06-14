"""Live direct-Anthropic-API enrichers (ENH-003 phase 2) — env-gated.

Set ``CKG_LIVE_ANTHROPIC=1`` with ``ANTHROPIC_API_KEY`` to run. Verifies the
judge confirms a clear Repository and tracks cost, and the summarizer returns
non-empty prose — the non-AWS path end-to-end (ENH-003 acceptance)."""

from __future__ import annotations

import os

import pytest

from agentforge_graph.enrich.anthropic import AnthropicClaudeJudge, AnthropicClaudeSummarizer
from agentforge_graph.enrich.heuristics import Candidate
from agentforge_graph.enrich.summarizer import FileContext

pytestmark = pytest.mark.skipif(
    os.environ.get("CKG_LIVE_ANTHROPIC") != "1",
    reason="live Anthropic API; set CKG_LIVE_ANTHROPIC=1 with ANTHROPIC_API_KEY",
)


async def test_live_anthropic_judge_confirms_repository() -> None:
    judge = AnthropicClaudeJudge()
    candidate = Candidate(
        symbol_id="ckg py r app.py OrderRepository#",
        name="OrderRepository",
        kind="Class",
        signature="class OrderRepository:",
        methods=[("get", "def get(self, id):"), ("save", "def save(self, o):")],
        patterns=["Repository"],
        evidence=["CRUD methods over a single aggregate"],
    )
    verdicts = await judge.judge(candidate)
    assert any(v.pattern == "Repository" and v.is_match for v in verdicts)
    assert judge.cost_usd > 0


async def test_live_anthropic_summarizer_returns_prose() -> None:
    summ = AnthropicClaudeSummarizer()
    summary = await summ.summarize_file(
        FileContext(
            path="orders/repo.py",
            symbols=[("OrderRepository", "class OrderRepository:")],
            imports=["sqlalchemy"],
        ),
        max_words=40,
    )
    assert summary.text.strip()
    assert summ.cost_usd > 0
