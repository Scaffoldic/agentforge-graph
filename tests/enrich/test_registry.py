"""ENH-003: judge + summarizer selection goes through the provider registry —
the credential-free ``scripted`` built-in, unknown-provider error, and a
third-party entry-point provider. No model creds touched (no ``bedrock`` path)."""

from __future__ import annotations

import pytest

import agentforge_graph.providers as providers
from agentforge_graph.config import EnrichConfig
from agentforge_graph.enrich import judge_from_config, summarizer_from_config
from agentforge_graph.enrich.judge import PatternJudge, ScriptedJudge
from agentforge_graph.enrich.summarizer import ScriptedSummarizer, Summarizer
from agentforge_graph.providers import ProviderNotFound


def test_scripted_judge_builtin() -> None:
    j = judge_from_config(EnrichConfig(provider="scripted"))
    assert isinstance(j, ScriptedJudge)
    assert isinstance(j, PatternJudge)  # satisfies the runtime-checkable protocol


def test_scripted_summarizer_builtin() -> None:
    s = summarizer_from_config(EnrichConfig(provider="scripted"))
    assert isinstance(s, ScriptedSummarizer)
    assert isinstance(s, Summarizer)


def test_unknown_judge_provider_raises() -> None:
    with pytest.raises(ProviderNotFound) as exc:
        judge_from_config(EnrichConfig(provider="nope"))
    assert "judge" in str(exc.value)


def test_unknown_summarizer_provider_raises() -> None:
    with pytest.raises(ProviderNotFound) as exc:
        summarizer_from_config(EnrichConfig(provider="nope"))
    assert "summarizer" in str(exc.value)


def test_third_party_judge_via_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    sentinel = ScriptedJudge()

    class _EP:
        name = "custom"

        @staticmethod
        def load() -> object:
            return lambda cfg: sentinel

    monkeypatch.setattr(
        providers, "entry_points", lambda *, group: [_EP()] if "judge" in group else []
    )
    assert judge_from_config(EnrichConfig(provider="custom")) is sentinel


def test_default_provider_is_bedrock() -> None:
    # Default stays Bedrock so existing deployments are unchanged by ENH-003.
    assert EnrichConfig().provider == "bedrock"
