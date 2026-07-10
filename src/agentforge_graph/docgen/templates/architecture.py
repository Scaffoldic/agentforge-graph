"""The ``architecture`` template — a system overview skeleton (feat-016)."""

from __future__ import annotations

from ..types import DocType
from .base import Template

ARCHITECTURE_TEMPLATE = Template(
    doc_type=DocType.ARCHITECTURE,
    title="Architecture Overview",
    sections=(
        "Overview",
        "Layers & Components",
        "Key Modules",
        "Entry Points & Interfaces",
        "Data & Framework Topology",
    ),
    guidance=(
        "Describe how the system is structured and how its parts fit together — "
        "orient a new engineer. Prefer the most central symbols and the framework "
        "topology (routes/models) as anchors."
    ),
)
