"""ckg serve-mcp CLI dispatch (serve_mcp stubbed so it doesn't block)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.cli import build_parser, main


def test_serve_mcp_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    async def fake_serve(
        repo_path: str = ".", config: object = None, refresh_on_call: bool = False
    ) -> None:
        seen["repo"] = repo_path
        seen["refresh"] = refresh_on_call

    monkeypatch.setattr("agentforge_graph.serve.serve_mcp", fake_serve)
    rc = main(["serve-mcp", "--repo", str(tmp_path), "--refresh-on-call"])
    assert rc == 0
    assert seen["repo"] == str(tmp_path)
    assert seen["refresh"] is True


def test_serve_mcp_parses() -> None:
    args = build_parser().parse_args(["serve-mcp", "--repo", "."])
    assert args.command == "serve-mcp"
    assert args.refresh_on_call is False
