"""Agent-adapter registry (feat-013).

``ckg setup`` is agent-agnostic at its core; each supported coding agent is a
small **adapter** — detection + where it reads MCP config — registered here.
This mirrors the storage-driver registry (ADR-0006) and the provider registry
(ENH-003): built-ins ship in-tree, third parties register out-of-tree via an
entry-point group.

The ``setup`` package is the deliberate ADR-0001 **framework layer** (like
``serve``); these adapters touch only the filesystem, no engine internals.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from importlib.metadata import entry_points
from pathlib import Path
from typing import Protocol, TypedDict, runtime_checkable

ADAPTER_GROUP = "agentforge_graph.agent_adapters"

# Recognised scopes: where the MCP entry is written.
#   project → a repo-root .mcp.json (default; shareable/committable, per-repo)
#   user    → the agent's user-global config (e.g. ~/.claude.json)
SCOPES = ("project", "user")


@dataclass(frozen=True)
class AgentTarget:
    """Identity of a supported agent."""

    key: str  # stable adapter key, e.g. "claude_code"
    display: str  # human label, e.g. "Claude Code"


class Detection(TypedDict):
    """Result of probing for an agent on this machine."""

    installed: bool
    note: str  # where it was found, or why it was skipped


@runtime_checkable
class AgentAdapter(Protocol):
    """A coding-agent integration: detect it, and say where it reads MCP config.

    Adapters are conservative — an ambiguous probe reports ``installed: False``
    with a note (never a write). Writing is done by the merge layer (chunk 2),
    not the adapter, so adapters stay pure/­testable.
    """

    target: AgentTarget

    def detect(self) -> Detection: ...

    def config_path(self, repo: Path, scope: str) -> Path | None:
        """The file this agent reads for ``scope`` (``None`` ⇒ scope unsupported)."""
        ...


_BUILTINS: dict[str, AgentAdapter] = {}
_builtins_loaded = False


def _ensure_builtins() -> None:
    """Populate the built-in adapters lazily (breaks the registry↔adapter import
    cycle — adapters import their types from this module)."""
    global _builtins_loaded
    if _builtins_loaded:
        return
    from .adapters.claude_code import ClaudeCodeAdapter
    from .adapters.mcp_json import McpJsonAdapter

    for adapter in (McpJsonAdapter(), ClaudeCodeAdapter()):
        _BUILTINS.setdefault(adapter.target.key, adapter)
    _builtins_loaded = True


def register_adapter(adapter: AgentAdapter) -> None:
    """Register (or override) an adapter by its target key. For tests and
    out-of-tree integrations that prefer code over an entry point."""
    _ensure_builtins()
    _BUILTINS[adapter.target.key] = adapter


def _load_entrypoint_adapters() -> None:
    for ep in entry_points(group=ADAPTER_GROUP):
        if ep.name in _BUILTINS:
            continue
        obj = ep.load()
        _BUILTINS[ep.name] = obj() if isinstance(obj, type) else obj


def all_adapters(allow: list[str] | None = None) -> list[AgentAdapter]:
    """All known adapters (built-in + entry-point), optionally filtered to an
    ``allow`` list of keys. An empty/None ``allow`` returns everything.

    (Named ``all_adapters`` not ``adapters`` so it doesn't collide with the
    ``setup.adapters`` subpackage in the package namespace.)"""
    _ensure_builtins()
    _load_entrypoint_adapters()
    items = list(_BUILTINS.values())
    if allow:
        wanted = set(allow)
        items = [a for a in items if a.target.key in wanted]
    return items


def get_adapter(key: str) -> AgentAdapter | None:
    """The adapter for ``key``, or ``None`` if unknown."""
    _ensure_builtins()
    _load_entrypoint_adapters()
    return _BUILTINS.get(key)


# Re-exported for adapters that probe PATH (kept here so adapters import one place).
which = shutil.which
