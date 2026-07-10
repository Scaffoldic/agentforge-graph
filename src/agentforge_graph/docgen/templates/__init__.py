"""Doc templates (feat-016) — registered by doc type on import."""

from __future__ import annotations

from .ai_context import AI_CONTEXT_TEMPLATE
from .architecture import ARCHITECTURE_TEMPLATE
from .base import SYSTEM_PROMPT, TEMPLATES, Template, get_template, register_template
from .component import COMPONENT_TEMPLATE
from .design import DESIGN_TEMPLATE

register_template(ARCHITECTURE_TEMPLATE)
register_template(AI_CONTEXT_TEMPLATE)
register_template(COMPONENT_TEMPLATE)
register_template(DESIGN_TEMPLATE)

__all__ = [
    "SYSTEM_PROMPT",
    "TEMPLATES",
    "Template",
    "get_template",
    "register_template",
    "ARCHITECTURE_TEMPLATE",
    "AI_CONTEXT_TEMPLATE",
    "COMPONENT_TEMPLATE",
    "DESIGN_TEMPLATE",
]
