"""Dual binding: the same nine ``Tool`` instances power both
``code_graph_tools`` (for ``Agent(tools=…)``) and ``serve_mcp`` (an MCP server).
One definition, every call site — no toolset drift.

The MCP server runs over two transports (feat-008):

- **stdio** (default) — the client launches ``ckg serve-mcp`` as a subprocess
  (``command``/``args`` in an ``mcpServers`` block; ``claude mcp add``).
- **http** — a long-running streamable-HTTP server (mounted at ``/mcp`` under
  uvicorn) that clients connect to by ``url``. Same tools, same guardrails.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from agentforge_core.contracts.tool import Tool
from agentforge_mcp import MCPServer

from .engine import EngineProvider, _Engine
from .federation import FederatedEngine
from .http_runner import BearerAuthMiddleware, is_loopback
from .tools import ALL_TOOLS, CkgServicesMap, CkgTrace
from .workspace import WorkspaceConfig

Transport = Literal["stdio", "http"]


def _tools_for(engine: EngineProvider) -> list[Tool]:
    # ALL_TOOLS holds concrete Tool subclasses; mypy joins them to the abstract
    # base and can't see that, hence the abstract ignore.
    return [tool_cls(engine) for tool_cls in ALL_TOOLS]  # type: ignore[abstract]


def code_graph_tools(repo_path: str | Path = ".", config: str | Path | None = None) -> list[Tool]:
    """The CKG toolset as native AgentForge ``Tool`` instances, sharing one
    lazily-opened engine. Pass straight to ``Agent(tools=code_graph_tools("."))``."""
    return _tools_for(_Engine(repo_path, config))


def federated_tools(workspace: str | Path) -> list[Tool]:
    """The CKG toolset over a **workspace** of members (ENH-020). Survey tools
    fan across every member; pinpoint tools take a ``service`` to pick one; plus
    the federation-only ``ckg_services_map`` (cross-service call graph). One
    endpoint for the whole org."""
    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(workspace))
    # the cross-service tools are appended only here — single-repo tool set stays v1.
    return [*_tools_for(fed), CkgServicesMap(fed), CkgTrace(fed)]


def build_mcp_server(
    repo_path: str | Path = ".",
    config: str | Path | None = None,
    *,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_on_call: bool = False,
    auth_token: str = "",
    allow_unauthenticated: bool = False,
    workspace: str | Path | None = None,
) -> MCPServer:
    """Build (but don't serve) the MCP server with the CKG tools, over the
    chosen ``transport`` (``stdio`` default, or ``http`` at ``host:port``).

    HTTP auth (ENH-005): ``auth_token`` (or ``$CKG_HTTP_AUTH_TOKEN``) requires a
    matching ``Authorization: Bearer …`` on every request — off by default to
    preserve the localhost loop. Binding a **non-loopback** host with no token is
    refused unless ``allow_unauthenticated`` (a loud, deliberate opt-in), so an
    exposed port is never silently wide open. ``refresh_on_call`` is a no-op at
    0.1 (tools are read-only; cheap refresh is feat-004)."""
    if transport not in ("stdio", "http"):
        msg = f"unknown MCP transport {transport!r}; use 'stdio' or 'http'"
        raise ValueError(msg)
    # Resolve + validate auth before opening the engine, so a misconfigured bind
    # fails fast (not after the index is loaded).
    token = auth_token or os.environ.get("CKG_HTTP_AUTH_TOKEN", "")
    if transport == "http" and not token and not is_loopback(host) and not allow_unauthenticated:
        msg = (
            f"refusing to serve the HTTP MCP transport on non-loopback host {host!r} "
            "with no auth: set serve.http_auth_token / $CKG_HTTP_AUTH_TOKEN, or pass "
            "--allow-unauthenticated to bind it open on purpose"
        )
        raise ValueError(msg)
    # ENH-020: a workspace serves many members from one endpoint (federated);
    # otherwise the single repo.
    tools = federated_tools(workspace) if workspace else code_graph_tools(repo_path, config)
    allowed = tuple(t.name for t in tools)
    if transport == "stdio":
        # no auth: the client owns the subprocess (stdin/stdout).
        return MCPServer.from_stdio(tools=tools, allowed=allowed, server_name="ckg")
    # HTTP: a bearer-token gate rides the framework's middleware seam
    # (agentforge-mcp >=0.3 from_http(middleware=…)); no auth → the plain app.
    middleware = None
    if token:
        from starlette.middleware import Middleware

        middleware = [Middleware(BearerAuthMiddleware, token=token)]
    return MCPServer.from_http(
        tools=tools,
        host=host,
        port=port,
        allowed=allowed,
        server_name="ckg",
        middleware=middleware,
    )


async def serve_mcp(
    repo_path: str | Path = ".",
    config: str | Path | None = None,
    *,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_on_call: bool = False,
    auth_token: str = "",
    allow_unauthenticated: bool = False,
    workspace: str | Path | None = None,
) -> None:
    """Run the CKG MCP server (blocks until stopped). ``transport='http'`` serves
    streamable-HTTP at ``http://{host}:{port}/mcp``; the default ``stdio`` serves
    over stdin/stdout for a subprocess client. See ``build_mcp_server`` for the
    ``auth_token`` / ``allow_unauthenticated`` HTTP-auth semantics (ENH-005)."""
    await build_mcp_server(
        repo_path,
        config,
        transport=transport,
        host=host,
        port=port,
        refresh_on_call=refresh_on_call,
        auth_token=auth_token,
        allow_unauthenticated=allow_unauthenticated,
        workspace=workspace,
    ).serve()
