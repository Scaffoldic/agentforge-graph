"""Doc-type recipes (feat-016) — the seed assemblers, registered by doc type.

Importing this package registers every built-in recipe into ``RECIPES``. A new
doc type registers itself here without touching the generator or runner.
"""

from __future__ import annotations

from .ai_context import AiContextRecipe
from .architecture import ArchitectureRecipe
from .base import RECIPES, Recipe, get_recipe, register
from .component import ComponentRecipe
from .design import DesignRecipe

register(ArchitectureRecipe())
register(AiContextRecipe())
register(ComponentRecipe())
register(DesignRecipe())

__all__ = [
    "RECIPES",
    "Recipe",
    "get_recipe",
    "register",
    "ArchitectureRecipe",
    "AiContextRecipe",
    "ComponentRecipe",
    "DesignRecipe",
]
