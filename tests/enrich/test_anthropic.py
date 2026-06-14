"""Direct Anthropic-API enrichers (ENH-003 phase 2) — deterministic, no network.

Covers model-id normalisation, the AnthropicClient transport (fake SDK), lazy
client construction (the real SDK builds offline — no call is made), and that the
provider registry resolves ``anthropic`` credential-free."""

from __future__ import annotations

from typing import Any

import pytest

from agentforge_graph.config import EnrichConfig
from agentforge_graph.enrich import judge_from_config, summarizer_from_config
from agentforge_graph.enrich.anthropic import AnthropicClaudeJudge, AnthropicClaudeSummarizer
from agentforge_graph.enrich.anthropic_client import AnthropicClient, api_model_id


def test_api_model_id_normalises_bedrock_ids() -> None:
    assert (
        api_model_id("us.anthropic.claude-haiku-4-5-20251001-v1:0") == "claude-haiku-4-5-20251001"
    )
    assert api_model_id("eu.anthropic.claude-sonnet-4-6-v1:0") == "claude-sonnet-4-6"
    assert api_model_id("anthropic.claude-opus-4-8") == "claude-opus-4-8"
    # already an API id → unchanged (idempotent)
    assert api_model_id("claude-haiku-4-5-20251001") == "claude-haiku-4-5-20251001"


class _FakeMessage:
    def model_dump(self) -> dict[str, Any]:
        return {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
        }


class _FakeMessages:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> _FakeMessage:
        self.kwargs = kwargs
        return _FakeMessage()


class _FakeSDK:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


async def test_client_invoke_threads_tools_and_tracks_cost() -> None:
    client = AnthropicClient("us.anthropic.claude-haiku-4-5-20251001-v1:0")
    client._client = _FakeSDK()  # bypass the lazy SDK import
    payload = await client.invoke(
        "sys", "usr", tools=[{"name": "submit_verdicts"}], tool_name="submit_verdicts"
    )
    assert payload["content"][0]["text"] == "ok"
    # haiku-4-5 = $1/M input → 1M tokens = $1.00
    assert client.cost_usd == pytest.approx(1.0)
    assert client.model == "claude-haiku-4-5-20251001"
    sent = client._client.messages.kwargs
    assert sent is not None
    assert sent["model"] == "claude-haiku-4-5-20251001"
    assert sent["tool_choice"] == {"type": "tool", "name": "submit_verdicts"}


def test_client_builds_real_sdk_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    # The anthropic SDK ships with the base install; constructing a client makes
    # no network call, so we can cover the lazy-build branch here.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = AnthropicClient("claude-haiku-4-5-20251001", base_url="https://example.test")
    sdk = client._anthropic()
    assert sdk is not None
    assert client._anthropic() is sdk  # cached


def test_registry_resolves_anthropic_credential_free() -> None:
    cfg = EnrichConfig(provider="anthropic")  # default Bedrock model id
    judge = judge_from_config(cfg)
    summ = summarizer_from_config(cfg)
    assert isinstance(judge, AnthropicClaudeJudge)
    assert isinstance(summ, AnthropicClaudeSummarizer)
    # the default Bedrock id is normalised to its API form
    assert judge.model == "claude-haiku-4-5-20251001"
    assert summ.model == "claude-haiku-4-5-20251001"
