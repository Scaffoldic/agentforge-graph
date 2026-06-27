"""Generic ``.mcp.json`` adapter (feat-013).

``.mcp.json`` at the repo root is the portable, emerging MCP-client standard:
Claude Code and other ``.mcp.json``-aware agents read it, and committing it
wires the whole team. This adapter is the **project-scope target** even when no
specific agent is detected — writing the standard file is always useful.

It has no user-global form (there is no single generic global config), so
``config_path(scope="user")`` is ``None``.
"""

from __future__ import annotations

from pathlib import Path

from ..registry import AgentTarget, Detection


class McpJsonAdapter:
    target = AgentTarget(key="mcp_json", display="Project .mcp.json (MCP standard)")

    def detect(self) -> Detection:
        # Not an installed *agent* — a passive, always-available target. Reported
        # so the user sees the portable file will be written regardless.
        return {"installed": True, "note": "portable .mcp.json — read by any MCP-aware agent"}

    def config_path(self, repo: Path, scope: str) -> Path | None:
        return repo / ".mcp.json" if scope == "project" else None
