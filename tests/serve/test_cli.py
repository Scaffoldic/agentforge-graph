"""ckg serve-mcp CLI dispatch (serve_mcp stubbed so it doesn't block)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.cli import build_parser, main


def _stub_serve(seen: dict[str, object]) -> object:
    async def fake_serve(
        repo_path: str = ".",
        config: object = None,
        *,
        transport: str = "stdio",
        host: str = "127.0.0.1",
        port: int = 8765,
        refresh_on_call: bool = False,
        auth_token: str = "",
        allow_unauthenticated: bool = False,
        workspace: object = None,
    ) -> None:
        seen.update(
            repo=repo_path,
            transport=transport,
            host=host,
            port=port,
            refresh=refresh_on_call,
            auth_token=auth_token,
            allow_unauthenticated=allow_unauthenticated,
            workspace=workspace,
        )

    return fake_serve


def test_serve_mcp_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr("agentforge_graph.serve.serve_mcp", _stub_serve(seen))
    rc = main(["serve-mcp", "--repo", str(tmp_path), "--refresh-on-call"])
    assert rc == 0
    assert seen["repo"] == str(tmp_path)
    assert seen["refresh"] is True
    assert seen["transport"] == "stdio"  # default when no flag / no ckg.yaml


def test_serve_mcp_http_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr("agentforge_graph.serve.serve_mcp", _stub_serve(seen))
    rc = main(
        [
            "serve-mcp",
            "--repo",
            str(tmp_path),
            "--transport",
            "http",
            "--host",
            "0.0.0.0",
            "--port",
            "9100",
        ]
    )
    assert rc == 0
    assert seen["transport"] == "http"
    assert seen["host"] == "0.0.0.0"
    assert seen["port"] == 9100


def test_serve_mcp_auth_flags_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr("agentforge_graph.serve.serve_mcp", _stub_serve(seen))
    rc = main(
        ["serve-mcp", "--repo", str(tmp_path), "--transport", "http",
         "--auth-token", "sekret", "--allow-unauthenticated"]
    )  # fmt: skip
    assert rc == 0
    assert seen["auth_token"] == "sekret"
    assert seen["allow_unauthenticated"] is True


def test_serve_mcp_parses() -> None:
    args = build_parser().parse_args(["serve-mcp", "--repo", "."])
    assert args.command == "serve-mcp"
    assert args.refresh_on_call is False
    assert args.transport is None  # resolved from ckg.yaml / default at dispatch
    assert args.auth_token == ""
    assert args.allow_unauthenticated is False
