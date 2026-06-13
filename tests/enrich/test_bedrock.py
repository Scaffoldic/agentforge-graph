"""BedrockClaudeJudge parsing/cost/prompt — deterministic, no AWS (the shared
client's invoke is monkeypatched). The live path is covered by test_live.py."""

from __future__ import annotations

import pytest

from agentforge_graph.enrich.bedrock import BedrockClaudeJudge
from agentforge_graph.enrich.bedrock_client import price_for as _price_for
from agentforge_graph.enrich.heuristics import Candidate


def _candidate() -> Candidate:
    return Candidate(
        symbol_id="ckg py repo app.py OrderRepo#",
        name="OrderRepo",
        kind="Class",
        signature="class OrderRepo:",
        methods=[("get", "def get(self, id):"), ("save", "def save(self, o):")],
        patterns=["Repository", "Service"],
        evidence=["CRUD methods"],
    )


def test_price_table_matches_model() -> None:
    assert _price_for("us.anthropic.claude-haiku-4-5-20251001-v1:0") == (1.0, 5.0)
    assert _price_for("anthropic.claude-sonnet-4-6") == (3.0, 15.0)
    assert _price_for("something-unknown") == (1.0, 5.0)  # default


def test_parse_extracts_verdicts_and_usage() -> None:
    payload = {
        "content": [
            {
                "type": "tool_use",
                "name": "submit_verdicts",
                "input": {
                    "verdicts": [
                        {
                            "pattern": "Repository",
                            "is_match": True,
                            "confidence": 0.95,
                            "rationale": "crud",
                        },
                        {
                            "pattern": "Service",
                            "is_match": False,
                            "confidence": 2.0,
                            "rationale": "no",
                        },
                    ]
                },
            }
        ],
    }
    verdicts = BedrockClaudeJudge._parse(payload)
    assert {v.pattern for v in verdicts} == {"Repository", "Service"}
    assert verdicts[1].confidence == 1.0  # clamped from 2.0 into [0,1]


async def test_judge_filters_to_nominated_and_tracks_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = BedrockClaudeJudge()
    canned = {
        "content": [
            {
                "type": "tool_use",
                "input": {
                    "verdicts": [
                        {
                            "pattern": "Repository",
                            "is_match": True,
                            "confidence": 0.9,
                            "rationale": "x",
                        },
                        {
                            "pattern": "Builder",
                            "is_match": True,
                            "confidence": 0.9,
                            "rationale": "y",
                        },
                    ]
                },
            }
        ],
        "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
    }

    async def fake_invoke(system, user, tools=None, tool_name=None):  # type: ignore[no-untyped-def]
        judge._client.cost_usd += 1.0  # 1M input tokens × $1/M
        return canned

    monkeypatch.setattr(judge._client, "invoke", fake_invoke)
    verdicts = await judge.judge(_candidate())
    # Builder wasn't nominated for this candidate → filtered out
    assert {v.pattern for v in verdicts} == {"Repository"}
    assert judge.cost_usd == pytest.approx(1.0)


async def test_judge_no_patterns_is_free() -> None:
    judge = BedrockClaudeJudge()
    empty = Candidate(
        symbol_id="ckg py r f.py X#", name="X", kind="Class", signature="", methods=[]
    )
    assert await judge.judge(empty) == []
    assert judge.cost_usd == 0.0


def test_prompt_includes_evidence_and_methods() -> None:
    prompt = BedrockClaudeJudge()._prompt(_candidate())
    assert "OrderRepo" in prompt and "CRUD methods" in prompt and "get" in prompt
