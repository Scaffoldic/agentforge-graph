"""BedrockClient + BedrockClaudeSummarizer — deterministic (invoke monkeypatched,
no AWS). The live path is covered by the gated live tests."""

from __future__ import annotations

import pytest

from agentforge_graph.enrich.bedrock_client import BedrockClient, price_for, text_of
from agentforge_graph.enrich.bedrock_summarizer import BedrockClaudeSummarizer
from agentforge_graph.enrich.summarizer import FileContext


def test_price_for_and_text_of() -> None:
    assert price_for("us.anthropic.claude-haiku-4-5-20251001-v1:0") == (1.0, 5.0)
    assert price_for("anthropic.claude-sonnet-4-6") == (3.0, 15.0)
    payload = {"content": [{"type": "text", "text": "hello "}, {"type": "text", "text": "world"}]}
    assert text_of(payload) == "hello world"


async def test_client_invoke_accumulates_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    client = BedrockClient()
    canned = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
    }
    monkeypatch.setattr(client, "_invoke", lambda *a, **k: canned)
    out = await client.invoke("sys", "user")
    assert text_of(out) == "ok"
    assert client.cost_usd == pytest.approx(1.0)  # 1M input × $1/M


async def test_summarizer_uses_client(monkeypatch: pytest.MonkeyPatch) -> None:
    s = BedrockClaudeSummarizer()
    canned = {
        "content": [{"type": "text", "text": "a file that does X"}],
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }

    async def fake_invoke(system, user, tools=None, tool_name=None):  # type: ignore[no-untyped-def]
        s._client.cost_usd += 0.001
        return canned

    monkeypatch.setattr(s._client, "invoke", fake_invoke)
    fs = await s.summarize_file(FileContext(path="x.py", symbols=[("f", "def f():")]), 120)
    assert fs.text == "a file that does X" and fs.model == s.model
    rs = await s.summarize_repo("repo", [("x.py", fs.text)], 120)
    assert rs.text == "a file that does X"
    assert s.cost_usd == pytest.approx(0.002)
