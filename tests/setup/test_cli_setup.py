"""feat-013 chunk 3: `ckg setup` through the real CLI entry point."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge_graph.cli import main


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


def test_cli_print_writes_nothing(tmp_path: Path, capsys) -> None:
    rc = main(["setup", str(tmp_path), "--agent", "mcp_json", "--print"])
    assert rc == 0
    assert not (tmp_path / ".mcp.json").exists()
    assert "Plan" in capsys.readouterr().out


def test_cli_apply_no_check(tmp_path: Path) -> None:
    rc = main(["setup", str(tmp_path), "--agent", "mcp_json", "--yes", "--no-check"])
    assert rc == 0
    assert _read(tmp_path / ".mcp.json")["mcpServers"]["ckg"]["command"] == "ckg"


def test_cli_undo(tmp_path: Path) -> None:
    main(["setup", str(tmp_path), "--agent", "mcp_json", "--yes", "--no-check"])
    rc = main(["setup", str(tmp_path), "--agent", "mcp_json", "--undo"])
    assert rc == 0
    assert not (tmp_path / ".mcp.json").exists()


def test_cli_bind_safety_exit_2(tmp_path: Path, capsys) -> None:
    rc = main(
        [
            "setup",
            str(tmp_path),
            "--agent",
            "mcp_json",
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--yes",
            "--no-check",
        ]
    )
    assert rc == 2
    assert "bind-safety" in capsys.readouterr().err
