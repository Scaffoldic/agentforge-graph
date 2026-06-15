"""ENH-005: bearer-token auth for the HTTP MCP transport.

Always-on: the pure-ASGI BearerAuthMiddleware + the bind-safety guard in
build_mcp_server. Env-gated: a live HTTP server that rejects unauthenticated
requests (set CKG_LIVE_MCP_HTTP=1; needs the mcp SDK + a free port)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from agentforge_graph.serve.http_runner import BearerAuthMiddleware, is_loopback
from agentforge_graph.serve.server import build_mcp_server


class _Downstream:
    """A trivial ASGI app that records whether it was reached."""

    def __init__(self) -> None:
        self.reached = False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.reached = True
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})


async def _drive(mw: BearerAuthMiddleware, headers: list[tuple[bytes, bytes]]) -> list[dict]:
    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg: dict) -> None:
        sent.append(msg)

    await mw({"type": "http", "headers": headers}, receive, send)
    return sent


def _status(sent: list[dict]) -> int:
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


async def test_missing_token_is_401_and_downstream_not_reached() -> None:
    app = _Downstream()
    mw = BearerAuthMiddleware(app, "s3cret")
    sent = await _drive(mw, headers=[])
    assert _status(sent) == 401
    assert not app.reached


async def test_wrong_token_is_401() -> None:
    app = _Downstream()
    mw = BearerAuthMiddleware(app, "s3cret")
    sent = await _drive(mw, headers=[(b"authorization", b"Bearer nope")])
    assert _status(sent) == 401
    assert not app.reached


async def test_correct_token_passes_through() -> None:
    app = _Downstream()
    mw = BearerAuthMiddleware(app, "s3cret")
    sent = await _drive(mw, headers=[(b"authorization", b"Bearer s3cret")])
    assert _status(sent) == 200
    assert app.reached


async def test_non_http_scope_passes_through() -> None:
    reached = False

    async def app(scope: Any, receive: Any, send: Any) -> None:
        nonlocal reached
        reached = True

    mw = BearerAuthMiddleware(app, "s3cret")
    await mw({"type": "lifespan"}, None, None)
    assert reached  # lifespan must not be gated


def test_is_loopback() -> None:
    assert is_loopback("127.0.0.1") and is_loopback("localhost") and is_loopback("::1")
    assert not is_loopback("0.0.0.0") and not is_loopback("10.0.0.5")


# --- bind safety (no engine opened: the guard runs before code_graph_tools) ---


def test_nonloopback_without_token_is_refused() -> None:
    with pytest.raises(ValueError, match="non-loopback"):
        build_mcp_server(transport="http", host="0.0.0.0")


def test_nonloopback_open_optin_builds(tmp_path: Path) -> None:
    # allow_unauthenticated is the deliberate opt-in; builds (engine is lazy)
    server = build_mcp_server(
        repo_path=tmp_path, transport="http", host="0.0.0.0", allow_unauthenticated=True
    )
    assert server is not None


def test_nonloopback_with_token_builds(tmp_path: Path) -> None:
    server = build_mcp_server(repo_path=tmp_path, transport="http", host="0.0.0.0", auth_token="t")
    assert server is not None


def test_token_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CKG_HTTP_AUTH_TOKEN", "envtok")
    server = build_mcp_server(repo_path=tmp_path, transport="http", host="0.0.0.0")
    assert server is not None  # env token satisfies the non-loopback guard


# --- live HTTP (env-gated) ----------------------------------------------------


@pytest.mark.skipif(not os.environ.get("CKG_LIVE_MCP_HTTP"), reason="set CKG_LIVE_MCP_HTTP=1")
async def test_live_http_rejects_unauthenticated(tmp_path: Path) -> None:
    import asyncio

    import httpx

    server = build_mcp_server(
        repo_path=tmp_path, transport="http", host="127.0.0.1", port=8799, auth_token="livetok"
    )
    serve_task = asyncio.create_task(server.serve())
    try:
        await asyncio.sleep(1.0)  # let uvicorn bind
        async with httpx.AsyncClient() as client:
            url = "http://127.0.0.1:8799/mcp"
            body = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
            no_auth = await client.post(url, json=body)
            assert no_auth.status_code == 401
            wrong = await client.post(url, json=body, headers={"Authorization": "Bearer nope"})
            assert wrong.status_code == 401
            # correct token gets PAST auth (the MCP layer then handles it — not 401)
            ok = await client.post(
                url,
                json=body,
                headers={
                    "Authorization": "Bearer livetok",
                    "Accept": "application/json, text/event-stream",
                },
            )
            assert ok.status_code != 401
    finally:
        await server.stop()
        serve_task.cancel()
