"""feat-013 chunk 2: structural MCP merge — create/idempotent/update/conflict,
undo, preservation, and ENH-005 bind-safety."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.setup.errors import SetupError
from agentforge_graph.setup.merge import (
    MARKER_KEY,
    MARKER_VALUE,
    build_entry,
    undo_entry,
    write_entry,
)


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


# --- build_entry / bind-safety ------------------------------------------------


def test_build_stdio_entry() -> None:
    e = build_entry(".")
    assert e["command"] == "ckg"
    assert e["args"] == ["serve-mcp", "--repo", "."]
    assert e[MARKER_KEY] == MARKER_VALUE


def test_build_http_loopback_ok() -> None:
    e = build_entry(".", transport="http", host="127.0.0.1", port=8765)
    assert e["url"] == "http://127.0.0.1:8765/mcp"
    assert e[MARKER_KEY] == MARKER_VALUE


def test_build_http_non_loopback_without_token_refused() -> None:
    with pytest.raises(SetupError, match="bind-safety"):
        build_entry(".", transport="http", host="0.0.0.0")


def test_build_http_non_loopback_with_token_ok() -> None:
    e = build_entry(".", transport="http", host="0.0.0.0", token="secret")
    assert e["url"] == "http://0.0.0.0:8765/mcp"


# --- write_entry --------------------------------------------------------------


def test_create_new_file(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    assert write_entry(p, build_entry(".")) == "create"
    doc = _read(p)
    assert doc["mcpServers"]["ckg"]["args"] == ["serve-mcp", "--repo", "."]


def test_idempotent(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    write_entry(p, build_entry("."))
    first = p.read_text()
    assert write_entry(p, build_entry(".")) == "noop"
    assert p.read_text() == first  # byte-identical


def test_update_replaces_our_entry(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    write_entry(p, build_entry("."))
    assert write_entry(p, build_entry("/abs/repo")) == "update"
    assert _read(p)["mcpServers"]["ckg"]["args"] == ["serve-mcp", "--repo", "/abs/repo"]


def test_preserves_other_servers_and_keys(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "extra": 7}))
    write_entry(p, build_entry("."))
    doc = _read(p)
    assert doc["mcpServers"]["other"] == {"command": "x"}  # untouched
    assert doc["extra"] == 7
    assert doc["mcpServers"]["ckg"][MARKER_KEY] == MARKER_VALUE


def test_conflict_on_unmarked_ckg(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"ckg": {"command": "mine"}}}))
    with pytest.raises(SetupError, match="you authored"):
        write_entry(p, build_entry("."))
    # the user's entry is untouched
    assert _read(p)["mcpServers"]["ckg"] == {"command": "mine"}


def test_force_overrides_conflict(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"ckg": {"command": "mine"}}}))
    assert write_entry(p, build_entry("."), force=True) == "update"
    assert _read(p)["mcpServers"]["ckg"][MARKER_KEY] == MARKER_VALUE


def test_unparsable_file_raises(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text("{ not json")
    with pytest.raises(SetupError, match="cannot parse"):
        write_entry(p, build_entry("."))


# --- undo_entry ---------------------------------------------------------------


def test_undo_absent(tmp_path: Path) -> None:
    assert undo_entry(tmp_path / ".mcp.json") == "absent"


def test_undo_skips_unmarked(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"ckg": {"command": "mine"}}}))
    assert undo_entry(p) == "skipped"
    assert _read(p)["mcpServers"]["ckg"] == {"command": "mine"}


def test_undo_removes_file_when_only_ours(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    write_entry(p, build_entry("."))
    assert undo_entry(p) == "removed-file"
    assert not p.exists()


def test_undo_keeps_other_servers(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}}))
    write_entry(p, build_entry("."))
    assert undo_entry(p) == "removed"
    doc = _read(p)
    assert "ckg" not in doc["mcpServers"]
    assert doc["mcpServers"]["other"] == {"command": "x"}


def test_undo_keeps_other_top_level_keys(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"extra": 7}))
    write_entry(p, build_entry("."))  # adds mcpServers.ckg alongside "extra"
    assert undo_entry(p) == "removed"
    doc = _read(p)
    assert doc == {"extra": 7}
