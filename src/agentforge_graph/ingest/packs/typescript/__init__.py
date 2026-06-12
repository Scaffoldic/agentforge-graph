"""The TypeScript language pack (Tier A — structure + import resolution)."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

TYPESCRIPT_PACK = LanguagePack(
    language="typescript",
    lang_slug="ts",
    grammar="typescript",
    extensions=(".ts",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,
            "def.function": NodeKind.FUNCTION,  # promoted to METHOD inside a class
        }
    ),
    module_style="relative",  # TS imports are path specifiers (./util), not dotted
)
