"""The JavaScript language pack (Tier A — structure + import resolution).

Shares the TS grammar family. The only structural delta is that JS
``class_declaration`` names are ``(identifier)``, not ``(type_identifier)``
(see ``structure.scm``). Like TS, JS module specifiers are path-based
(``./util``), so the pack uses ``module_style="relative"``.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

JAVASCRIPT_PACK = LanguagePack(
    language="javascript",
    lang_slug="js",
    grammar="javascript",
    extensions=(".js", ".jsx", ".mjs", ".cjs"),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,
            "def.function": NodeKind.FUNCTION,  # promoted to METHOD inside a class
            # ENH-008: arrow/function-bound consts + module-level const tables.
            "def.variable": NodeKind.VARIABLE,
        }
    ),
    module_style="relative",  # JS imports are path specifiers (./util), not dotted
)
