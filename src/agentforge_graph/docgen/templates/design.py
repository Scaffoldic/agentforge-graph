"""The ``design`` template — a "how it works + why" skeleton (feat-016)."""

from __future__ import annotations

from ..types import DocType
from .base import Template

DESIGN_TEMPLATE = Template(
    doc_type=DocType.DESIGN,
    title="Design Document",
    sections=(
        "Overview",
        "How It Works",
        "Key Components",
        "Design Decisions & Rationale",
    ),
    guidance=(
        "Explain how the subsystem in scope works and why it is built that way. "
        "Anchor 'why' claims in recorded decisions; anchor 'how' claims in the real "
        "symbols and their relationships. Do not speculate on rationale that is not "
        "grounded in a decision or the code."
    ),
)
