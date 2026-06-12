"""Built-in language packs. v0.1 ships Python (Tier A); the other nine
top-10 languages land as follow-up packs over this same harness."""

from __future__ import annotations

from agentforge_graph.ingest.pack import PackRegistry

from .python import PYTHON_PACK

BUILTIN_PACKS = [PYTHON_PACK]


def builtin_registry() -> PackRegistry:
    return PackRegistry(BUILTIN_PACKS)
