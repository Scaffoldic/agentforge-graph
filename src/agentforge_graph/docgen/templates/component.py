"""The ``component`` template — a per-module doc skeleton (feat-016)."""

from __future__ import annotations

from ..types import DocType
from .base import Template

COMPONENT_TEMPLATE = Template(
    doc_type=DocType.COMPONENT,
    title="Component Documentation",
    sections=(
        "Purpose",
        "Public API",
        "Key Types & Functions",
        "Dependencies & Framework Elements",
    ),
    guidance=(
        "Document the module in scope: what it is responsible for, the surface other "
        "code depends on, and its notable types/functions and framework elements "
        "(routes/models). Stay within the scope."
    ),
)
