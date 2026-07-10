"""Doc templates (feat-016) — registered by doc type on import."""

from __future__ import annotations

from .architecture import ARCHITECTURE_TEMPLATE
from .base import SYSTEM_PROMPT, TEMPLATES, Template, get_template, register_template

register_template(ARCHITECTURE_TEMPLATE)

__all__ = [
    "SYSTEM_PROMPT",
    "TEMPLATES",
    "Template",
    "get_template",
    "register_template",
    "ARCHITECTURE_TEMPLATE",
]
