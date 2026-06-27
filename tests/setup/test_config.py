"""feat-013 chunk 0: the ``setup:`` config block."""

from __future__ import annotations

from agentforge_graph.config import ResolvedConfig, SetupConfig, block_keys


def test_defaults() -> None:
    c = SetupConfig()
    assert c.scope == "project"
    assert c.transport == "stdio"
    assert c.install_hooks is False
    assert c.agents == []


def test_key_auto_registered() -> None:
    # block_keys() drives the ENH-022 cascade; a new block must appear with no
    # hand-maintained list.
    assert "setup" in block_keys()


def test_loads_from_section() -> None:
    cfg = ResolvedConfig(section={"setup": {"scope": "user", "agents": ["claude_code"]}})
    c = SetupConfig.load(cfg)
    assert c.scope == "user"
    assert c.agents == ["claude_code"]


def test_unknown_keys_ignored() -> None:
    # Lenient reader (extra='ignore') — a config written for a later chunk still
    # loads.
    cfg = ResolvedConfig(section={"setup": {"scope": "project", "future_knob": 1}})
    assert SetupConfig.load(cfg).scope == "project"
