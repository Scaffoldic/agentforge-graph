"""The C# language pack (Tier A — structure + namespace-prefix resolution).

C# differs from PHP/Java: `using App.Geo` imports a *namespace* (not a class), so
it resolves to every in-repo file declaring that namespace (and binds all their
symbols), rather than to one class FQN. Extracts class/struct/enum/record
(→Class), interface (→Interface), methods + constructors. Member calls
(`obj.M()`) stay unresolved (ADR-0004).
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

CSHARP_PACK = LanguagePack(
    language="csharp",
    lang_slug="cs",
    grammar="csharp",
    extensions=(".cs",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,  # class + struct + enum + record
            "def.interface": NodeKind.INTERFACE,
            "def.function": NodeKind.FUNCTION,  # method + constructor (promoted)
        }
    ),
    namespace_sep=".",
    namespace_import_prefix=True,  # `using App.Geo` = a namespace, not a class
)
