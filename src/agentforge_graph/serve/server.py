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

from pathlib import Path
from typing import Literal

from agentforge_core.contracts.tool import Tool
from agentforge_mcp import MCPServer

from .engine import _Engine
from .tools import ALL_TOOLS

Transport = Literal["stdio", "http"]


def code_graph_tools(repo_path: str | Path = ".", config: str | Path | None = None) -> list[Tool]:
    """The CKG toolset as native AgentForge ``Tool`` instances, sharing one
    lazily-opened engine. Pass straight to ``Agent(tools=code_graph_tools("."))``."""
    engine = _Engine(repo_path, config)
    # ALL_TOOLS holds concrete Tool subclasses; mypy joins them to the abstract
    # base and can't see that, hence the abstract ignore.
    return [tool_cls(engine) for tool_cls in ALL_TOOLS]  # type: ignore[abstract]


def build_mcp_server(
    repo_path: str | Path = ".",
    config: str | Path | None = None,
    *,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_on_call: bool = False,
) -> MCPServer:
    """Build (but don't serve) the MCP server with the CKG tools, over the
    chosen ``transport`` (``stdio`` default, or ``http`` at ``host:port``).
    ``refresh_on_call`` is accepted but a no-op at 0.1 (tools are read-only;
    cheap refresh is feat-004)."""
    if transport not in ("stdio", "http"):
        msg = f"unknown MCP transport {transport!r}; use 'stdio' or 'http'"
        raise ValueError(msg)
    tools = code_graph_tools(repo_path, config)
    allowed = tuple(t.name for t in tools)
    if transport == "http":
        return MCPServer.from_http(
            tools=tools, host=host, port=port, allowed=allowed, server_name="ckg"
        )
    return MCPServer.from_stdio(tools=tools, allowed=allowed, server_name="ckg")


async def serve_mcp(
    repo_path: str | Path = ".",
    config: str | Path | None = None,
    *,
    transport: Transport = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    refresh_on_call: bool = False,
) -> None:
    """Run the CKG MCP server (blocks until stopped). ``transport='http'`` serves
    streamable-HTTP at ``http://{host}:{port}/mcp``; the default ``stdio`` serves
    over stdin/stdout for a subprocess client."""
    await build_mcp_server(
        repo_path,
        config,
        transport=transport,
        host=host,
        port=port,
        refresh_on_call=refresh_on_call,
    ).serve()
