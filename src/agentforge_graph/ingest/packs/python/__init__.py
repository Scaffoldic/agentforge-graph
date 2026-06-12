"""The Python language pack (Tier A — structure + import resolution)."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

PYTHON_PACK = LanguagePack(
    language="python",
    lang_slug="py",
    grammar="python",
    extensions=(".py",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,
            "def.function": NodeKind.FUNCTION,  # promoted to METHOD when nested in a class
        }
    ),
)
