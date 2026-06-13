"""ENH-003: the generic model-provider resolver — built-in, entry-point, and
unknown-name behaviour, shared by the embed/enrich registries."""

from __future__ import annotations

import pytest

import agentforge_graph.providers as providers
from agentforge_graph.providers import ProviderNotFound, resolve_provider


def test_builtin_wins() -> None:
    builtins = {"a": "builder-a", "b": "builder-b"}
    assert resolve_provider("a", builtins, "some.group", role="thing") == "builder-a"


def test_unknown_raises_with_helpful_message() -> None:
    with pytest.raises(ProviderNotFound) as exc:
        resolve_provider("nope", {"a": 1, "b": 2}, "g.roup", role="embedder")
    msg = str(exc.value)
    assert "nope" in msg
    assert "embedder" in msg
    assert "['a', 'b']" in msg  # built-ins listed, sorted
    assert "g.roup" in msg  # entry-point group named for third parties


def test_entry_point_resolves_when_not_builtin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A third-party provider registers under the group with no built-in change."""

    class _FakeEP:
        name = "thirdparty"

        @staticmethod
        def load() -> str:
            return "loaded-builder"

    def _fake_entry_points(*, group: str) -> list[_FakeEP]:
        assert group == "x.group"
        return [_FakeEP()]

    monkeypatch.setattr(providers, "entry_points", _fake_entry_points)
    out = resolve_provider("thirdparty", {"builtin": 0}, "x.group", role="judge")
    assert out == "loaded-builder"
