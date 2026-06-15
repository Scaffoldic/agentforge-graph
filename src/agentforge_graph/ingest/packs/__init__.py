"""Built-in language packs. v0.1 ships Python/TypeScript/JavaScript/Go (Tier A);
the rest of the top-10 languages land as follow-up packs over this same harness."""

from __future__ import annotations

from agentforge_graph.ingest.pack import PackRegistry

from .go import GO_PACK
from .java import JAVA_PACK
from .javascript import JAVASCRIPT_PACK
from .php import PHP_PACK
from .python import PYTHON_PACK
from .ruby import RUBY_PACK
from .typescript import TYPESCRIPT_PACK

BUILTIN_PACKS = [
    PYTHON_PACK,
    TYPESCRIPT_PACK,
    JAVASCRIPT_PACK,
    GO_PACK,
    RUBY_PACK,
    PHP_PACK,
    JAVA_PACK,
]


def builtin_registry() -> PackRegistry:
    return PackRegistry(BUILTIN_PACKS)
