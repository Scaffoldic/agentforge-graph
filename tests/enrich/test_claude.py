"""Provider-neutral ClaudeJudge / ClaudeSummarizer (ENH-003 phase 2) — driven by
a stub ``ClaudeClient`` (no network). The Bedrock/Anthropic transports are tested
separately; this pins the shared prompt/parse/cost logic both reuse."""

from __future__ import annotations

from typing import Any

from agentforge_graph.enrich.claude import ClaudeClient, ClaudeJudge, ClaudeSummarizer
from agentforge_graph.enrich.heuristics import Candidate
from agentforge_graph.enrich.summarizer import FileContext


class _StubClient:
    """A canned-payload ClaudeClient that charges a fixed fee per call."""

    def __init__(self, payload: dict[str, Any], per_call_usd: float = 0.5) -> None:
        self._payload = payload
        self._fee = per_call_usd
        self.cost_usd = 0.0
        self.calls: list[tuple[str, str, Any, Any]] = []

    async def invoke(
        self,
        system: str,
        user: str,
        tools: list[dict[str, Any]] | None = None,
        tool_name: str | None = None,
    ) -> dict[str, Any]:
        self.cost_usd += self._fee
        self.calls.append((system, user, tools, tool_name))
        return self._payload


def _candidate() -> Candidate:
    return Candidate(
        symbol_id="ckg py r app.py OrderRepo#",
        name="OrderRepo",
        kind="Class",
        signature="class OrderRepo:",
        methods=[("get", "def get(self, id):")],
        patterns=["Repository", "Service"],
        evidence=["CRUD methods"],
    )


_VERDICT_PAYLOAD = {
    "content": [
        {
            "type": "tool_use",
            "input": {
                "verdicts": [
                    {
                        "pattern": "Repository",
                        "is_match": True,
                        "confidence": 0.9,
                        "rationale": "crud",
                    },
                    {"pattern": "Builder", "is_match": True, "confidence": 0.9, "rationale": "no"},
                ]
            },
        }
    ],
}


def test_stub_satisfies_protocol() -> None:
    assert isinstance(_StubClient(_VERDICT_PAYLOAD), ClaudeClient)


async def test_judge_filters_to_nominated_and_forces_tool() -> None:
    client = _StubClient(_VERDICT_PAYLOAD)
    judge = ClaudeJudge(client, model="claude-test")
    verdicts = await judge.judge(_candidate())
    # 'Builder' wasn't nominated for this candidate → filtered out
    assert {v.pattern for v in verdicts} == {"Repository"}
    assert judge.cost_usd == 0.5
    # the judge forces the submit_verdicts tool
    _, _, tools, tool_name = client.calls[0]
    assert tool_name == "submit_verdicts" and tools


async def test_judge_skips_malformed_verdicts() -> None:
    # a non-numeric confidence raises in float() → that verdict is dropped, the
    # well-formed one survives.
    payload = {
        "content": [
            {
                "type": "tool_use",
                "input": {
                    "verdicts": [
                        {"pattern": "Repository", "is_match": True, "confidence": "n/a"},
                        {
                            "pattern": "Service",
                            "is_match": True,
                            "confidence": 0.8,
                            "rationale": "ok",
                        },
                    ]
                },
            }
        ]
    }
    judge = ClaudeJudge(_StubClient(payload), model="claude-test")
    verdicts = await judge.judge(_candidate())
    assert {v.pattern for v in verdicts} == {"Service"}


async def test_judge_no_patterns_is_free() -> None:
    client = _StubClient(_VERDICT_PAYLOAD)
    judge = ClaudeJudge(client, model="claude-test")
    empty = Candidate(symbol_id="x", name="X", kind="Class", signature="", methods=[])
    assert await judge.judge(empty) == []
    assert judge.cost_usd == 0.0 and client.calls == []


async def test_summarizer_file_and_repo() -> None:
    client = _StubClient({"content": [{"type": "text", "text": "a summary"}]})
    summ = ClaudeSummarizer(client, model="claude-test")
    file_summary = await summ.summarize_file(
        FileContext(path="app.py", symbols=[("OrderRepo", "class OrderRepo:")], imports=["os"]),
        max_words=50,
    )
    assert file_summary.text == "a summary" and file_summary.model == "claude-test"
    repo_summary = await summ.summarize_repo("proj", [("app.py", "a summary")], max_words=80)
    assert repo_summary.text == "a summary"
    assert summ.cost_usd == 1.0  # two calls × 0.5
