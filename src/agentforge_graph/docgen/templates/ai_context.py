"""The ``ai-context`` template — a CLAUDE.md / AGENTS.md skeleton (feat-016)."""

from __future__ import annotations

from ..types import DocType
from .base import Template

AI_CONTEXT_TEMPLATE = Template(
    doc_type=DocType.AI_CONTEXT,
    title="AI Assistant Context (CLAUDE.md / AGENTS.md)",
    sections=(
        "Project Overview",
        "Architecture & Key Modules",
        "Conventions & Decisions",
        "How to Navigate",
    ),
    guidance=(
        "Write the orientation an AI coding assistant needs before working in this "
        "repository: what it is, how it is structured, the conventions/decisions to "
        "respect, and where to look. Keep it concise and navigational."
    ),
)
