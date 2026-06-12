"""Dual binding: the same six ``Tool`` instances power both
``code_graph_tools`` (for ``Agent(tools=…)``) and ``serve_mcp`` (an MCP stdio
server). One definition, two call sites — no toolset drift."""

from __future__ import annotations

from pathlib import Path

from agentforge_core.contracts.tool import Tool
from agentforge_mcp import MCPServer

from .engine import _Engine
from .tools import ALL_TOOLS


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
    refresh_on_call: bool = False,
) -> MCPServer:
    """Build (but don't serve) the MCP stdio server with the CKG tools.
    ``refresh_on_call`` is accepted but a no-op at 0.1 (tools are read-only;
    cheap refresh is feat-004)."""
    tools = code_graph_tools(repo_path, config)
    return MCPServer.from_stdio(
        tools=tools,
        allowed=tuple(t.name for t in tools),
        server_name="ckg",
    )


async def serve_mcp(
    repo_path: str | Path = ".",
    config: str | Path | None = None,
    refresh_on_call: bool = False,
) -> None:
    """Run the CKG MCP stdio server (blocks until stopped)."""
    await build_mcp_server(repo_path, config, refresh_on_call).serve()
