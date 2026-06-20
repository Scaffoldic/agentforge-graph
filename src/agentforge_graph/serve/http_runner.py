"""Bearer-token auth for the HTTP MCP transport (ENH-005).

The framework's ``MCPServer.from_http`` serves streamable-HTTP with **no auth** —
fine for the localhost/trusted-container default, but a wide-open surface on any
exposed port. ``agentforge-mcp`` (>=0.3) exposes a ``from_http(middleware=…)``
seam, so we pass :class:`BearerAuthMiddleware` as a Starlette ``Middleware`` and
let the framework build/serve the app — no need to reimplement the HTTP runner.

:class:`BearerAuthMiddleware` rejects any request lacking a matching
``Authorization: Bearer …`` with ``401`` (constant-time compare; the token is
never logged). The no-auth path stays 100% framework (unchanged default).
"""

from __future__ import annotations

import hmac
from typing import Any

# Hosts that don't need auth-by-default (the client owns the loopback surface).
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"})


def is_loopback(host: str) -> bool:
    return host in LOOPBACK_HOSTS


class BearerAuthMiddleware:
    """Pure-ASGI middleware: require ``Authorization: Bearer <token>`` on every
    HTTP request, else ``401``. Non-HTTP scopes (lifespan) pass through."""

    def __init__(self, app: Any, token: str) -> None:
        self._app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        provided = ""
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                provided = value.decode("latin-1")
                break
        # constant-time compare so a wrong token can't be timed out char by char.
        if not (provided and hmac.compare_digest(provided, self._expected)):
            await _send_401(send)
            return
        await self._app(scope, receive, send)


async def _send_401(send: Any) -> None:
    body = b'{"error":"unauthorized"}'
    await send(
        {
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"www-authenticate", b"Bearer"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
