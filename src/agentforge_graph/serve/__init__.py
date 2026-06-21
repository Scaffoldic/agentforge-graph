"""agentforge_graph.serve — MCP server & AgentForge tool API (feat-008).

The framework-facing serving layer: the nine read-only tools over feat-006/007,
bound both as native AgentForge ``Tool`` instances (``code_graph_tools``) and an
MCP server (``serve_mcp``) over **stdio or streamable-HTTP**, from one definition.
This package imports ``agentforge`` (the deliberate ADR-0001 exception).
"""

from __future__ import annotations

from .engine import TOOL_API_VERSION
from .server import build_mcp_server, code_graph_tools, federated_tools, serve_mcp

__all__ = [
    "TOOL_API_VERSION",
    "code_graph_tools",
    "federated_tools",
    "serve_mcp",
    "build_mcp_server",
]
