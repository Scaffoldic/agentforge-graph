"""feat-013 chunk 1: agent-adapter registry (built-ins, allow-filter,
override, third-party entry point)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

import agentforge_graph.setup.registry as reg
from agentforge_graph.setup import AgentTarget, all_adapters, get_adapter, register_adapter


@pytest.fixture(autouse=True)
def _isolate_registry() -> Iterator[None]:
    """Snapshot/restore the module-global registry so an override or entry-point
    test can't leak into the others."""
    saved = dict(reg._BUILTINS)
    saved_loaded = reg._builtins_loaded
    try:
        yield
    finally:
        reg._BUILTINS.clear()
        reg._BUILTINS.update(saved)
        reg._builtins_loaded = saved_loaded


def test_builtins_present() -> None:
    keys = {a.target.key for a in all_adapters()}
    assert {"mcp_json", "claude_code"} <= keys


def test_allow_filter() -> None:
    only = all_adapters(allow=["claude_code"])
    assert [a.target.key for a in only] == ["claude_code"]


def test_allow_empty_returns_all() -> None:
    assert {a.target.key for a in all_adapters(allow=[])} >= {"mcp_json", "claude_code"}


def test_get_adapter() -> None:
    assert get_adapter("claude_code") is not None
    assert get_adapter("does-not-exist") is None


def test_register_override() -> None:
    class _Fake:
        target = AgentTarget(key="claude_code", display="Fake")

        def detect(self) -> reg.Detection:
            return {"installed": False, "note": "fake"}

        def config_path(self, repo: Path, scope: str) -> Path | None:
            return None

    register_adapter(_Fake())
    a = get_adapter("claude_code")
    assert a is not None
    assert a.detect()["note"] == "fake"


def test_third_party_via_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Custom:
        target = AgentTarget(key="custom_agent", display="Custom")

        def detect(self) -> reg.Detection:
            return {"installed": True, "note": "custom"}

        def config_path(self, repo: Path, scope: str) -> Path | None:
            return repo / "custom.json"

    class _EP:
        name = "custom_agent"

        @staticmethod
        def load() -> object:
            return _Custom  # a class → registry instantiates it

    monkeypatch.setattr(
        reg, "entry_points", lambda *, group: [_EP()] if "agent_adapters" in group else []
    )
    keys = {a.target.key for a in all_adapters()}
    assert "custom_agent" in keys
    assert get_adapter("custom_agent") is not None
