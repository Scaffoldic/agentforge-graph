"""feat-014: ``ckg ci init`` — scaffold a CI workflow that keeps the shared,
central index fresh (CI as the single authoritative writer). GitHub first; the
scaffolder is provider-pluggable. Framework-free (ADR-0001)."""

from __future__ import annotations

from .github import MARKER, WORKFLOW_REL_PATH, render_workflow
from .scaffold import PROVIDERS, CiInitError, CiInitResult, scaffold_workflow

__all__ = [
    "MARKER",
    "WORKFLOW_REL_PATH",
    "render_workflow",
    "PROVIDERS",
    "CiInitError",
    "CiInitResult",
    "scaffold_workflow",
]
