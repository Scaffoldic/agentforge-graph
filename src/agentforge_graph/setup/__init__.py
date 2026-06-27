"""Agent auto-configuration (feat-013).

``ckg setup`` wires the CKG into a coding agent for the user: it writes the MCP
server entry (repo-root ``.mcp.json`` by default, ``--scope user`` for the
agent's global config) and, with ``--hooks``, appends a nudge block steering the
agent toward the ``ckg_*`` tools.

This package is the deliberate ADR-0001 **framework layer** (like ``serve``):
it may import the framework/MCP SDK; the deterministic engine stays untouched.

Public surface grows by chunk; chunk 1 ships the adapter registry + detection.
"""

from __future__ import annotations

from .errors import SetupError
from .plan import SetupPlan, build_plan, render_plan
from .registry import (
    SCOPES,
    AgentAdapter,
    AgentTarget,
    Detection,
    all_adapters,
    get_adapter,
    register_adapter,
)
from .runner import run_setup

__all__ = [
    "SCOPES",
    "AgentAdapter",
    "AgentTarget",
    "Detection",
    "SetupError",
    "SetupPlan",
    "all_adapters",
    "build_plan",
    "get_adapter",
    "register_adapter",
    "render_plan",
    "run_setup",
]
