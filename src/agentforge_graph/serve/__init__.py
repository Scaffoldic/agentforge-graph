"""agentforge_graph.serve — MCP server & AgentForge tool API (feat-008).

The framework-facing serving layer: the six read-only tools over feat-006/007,
bound both as native AgentForge ``Tool`` instances (``code_graph_tools``) and
an MCP stdio server (``serve_mcp``) from one definition. This package imports
``agentforge`` (the deliberate ADR-0001 exception).
"""

from __future__ import annotations

from .engine import TOOL_API_VERSION

__all__ = ["TOOL_API_VERSION"]
