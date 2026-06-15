"""Bearer-token auth for the HTTP MCP transport (ENH-005).

The framework's ``MCPServer.from_http`` serves streamable-HTTP with **no auth** —
fine for the localhost/trusted-container default, but a wide-open surface on any
exposed port. ``agentforge-mcp`` exposes no auth hook (see the framework wishlist
note), but ``from_http(runner=…)`` lets us inject a custom ``MCPServerRunner``.

So: the **no-auth** path stays 100% framework (unchanged default). When a token is
configured, ``serve`` uses :class:`CkgHttpRunner` here — it wires the MCP tools
exactly like the framework runner, but wraps the Starlette app in
:class:`BearerAuthMiddleware`, which rejects any request lacking a matching
``Authorization: Bearer …`` with ``401`` (constant-time compare; the token is
never logged). Drop this once the framework grows an auth hook.
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


class CkgHttpRunner:
    """An ``MCPServerRunner`` that serves the streamable-HTTP MCP transport with
    a bearer-token gate. Mirrors the framework's HTTP runner wiring (list/call
    tool dispatch + ``StreamableHTTPSessionManager`` under uvicorn) and wraps the
    app in :class:`BearerAuthMiddleware`."""

    def __init__(self, *, host: str, port: int, token: str, server_name: str = "ckg") -> None:
        from mcp.server import Server

        self._server = Server(server_name)
        self._host = host
        self._port = port
        self._token = token
        self._tools: dict[str, tuple[str, str, dict[str, Any], Any]] = {}
        self._uv_server: Any = None

    def register_tool(
        self, name: str, description: str, input_schema: dict[str, Any], handler: Any
    ) -> None:
        self._tools[name] = (name, description, dict(input_schema or {}), handler)

    async def serve(self) -> None:
        import contextlib

        import uvicorn
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
        from mcp.types import TextContent
        from mcp.types import Tool as MCPTool
        from starlette.applications import Starlette
        from starlette.routing import Mount

        registered = self._tools

        @self._server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
        async def _list() -> list[MCPTool]:
            return [
                MCPTool(name=n, description=d, inputSchema=s) for n, d, s, _ in registered.values()
            ]

        @self._server.call_tool()  # type: ignore[untyped-decorator]
        async def _call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
            tool = registered.get(name)
            if tool is None:
                raise ValueError(f"MCP server: unknown tool {name!r}")
            return [TextContent(type="text", text=await tool[3](arguments))]

        manager = StreamableHTTPSessionManager(app=self._server, json_response=True, stateless=True)

        async def _asgi(scope: Any, receive: Any, send: Any) -> None:
            await manager.handle_request(scope, receive, send)

        @contextlib.asynccontextmanager
        async def _lifespan(_app: Any) -> Any:
            async with manager.run():
                yield

        app = Starlette(routes=[Mount("/mcp", app=_asgi)], lifespan=_lifespan)
        guarded = BearerAuthMiddleware(app, self._token)
        config = uvicorn.Config(guarded, host=self._host, port=self._port, log_level="warning")
        self._uv_server = uvicorn.Server(config)
        await self._uv_server.serve()

    async def stop(self) -> None:
        if self._uv_server is not None:
            self._uv_server.should_exit = True
