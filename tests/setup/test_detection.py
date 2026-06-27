"""feat-013 chunk 1: adapter detection + config-path resolution."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.setup.adapters import claude_code as cc_mod
from agentforge_graph.setup.adapters.claude_code import ClaudeCodeAdapter
from agentforge_graph.setup.adapters.mcp_json import McpJsonAdapter


def test_claude_not_installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cc_mod, "which", lambda _name: None)
    d = ClaudeCodeAdapter().detect()
    assert d["installed"] is False
    assert "claude" in d["note"].lower()


def test_claude_detected_via_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cc_mod, "which", lambda _name: None)
    (tmp_path / ".claude.json").write_text("{}")
    d = ClaudeCodeAdapter().detect()
    assert d["installed"] is True
    assert ".claude.json" in d["note"]


def test_claude_detected_via_binary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(cc_mod, "which", lambda _name: "/usr/bin/claude")
    d = ClaudeCodeAdapter().detect()
    assert d["installed"] is True
    assert "PATH" in d["note"]


def test_claude_config_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    repo = tmp_path / "proj"
    a = ClaudeCodeAdapter()
    assert a.config_path(repo, "project") == repo / ".mcp.json"
    assert a.config_path(repo, "user") == tmp_path / ".claude.json"
    assert a.config_path(repo, "bogus") is None


def test_mcp_json_target(tmp_path: Path) -> None:
    a = McpJsonAdapter()
    assert a.detect()["installed"] is True
    assert a.config_path(tmp_path, "project") == tmp_path / ".mcp.json"
    assert a.config_path(tmp_path, "user") is None
