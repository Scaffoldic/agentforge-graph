"""Claude Code adapter (feat-013).

Detection is conservative — we only claim Claude Code is present if its
user-global config (``~/.claude.json``) exists or the ``claude`` binary is on
PATH. Config targets:

- **project** scope → ``<repo>/.mcp.json`` (Claude Code reads a project's
  ``.mcp.json``; committable + shareable).
- **user** scope → ``~/.claude.json`` (the user-global config; serves one
  absolute repo path).
"""

from __future__ import annotations

from pathlib import Path

from ..registry import AgentTarget, Detection, which


class ClaudeCodeAdapter:
    target = AgentTarget(key="claude_code", display="Claude Code")

    def detect(self) -> Detection:
        cfg = Path.home() / ".claude.json"
        if cfg.exists():
            return {"installed": True, "note": f"found {cfg}"}
        if which("claude"):
            return {"installed": True, "note": "found `claude` on PATH"}
        return {"installed": False, "note": "no ~/.claude.json and no `claude` on PATH"}

    def config_path(self, repo: Path, scope: str) -> Path | None:
        if scope == "project":
            return repo / ".mcp.json"
        if scope == "user":
            return Path.home() / ".claude.json"
        return None
