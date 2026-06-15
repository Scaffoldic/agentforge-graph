"""The Java language pack (Tier A — structure + namespace/FQN import resolution).

Java reuses the namespace/FQN mechanism (separator "."): a file declares a
`package`, and `import com.foo.Bar` resolves to the file declaring class `Bar` in
that package. Extracts class/enum/record (→Class), interface (→Interface),
methods + constructors. Method calls (`obj.m()`) stay unresolved (member access,
ADR-0004); since Java has no top-level functions, intra-class calls are method
dispatch too — the symbol graph + FQN dependency graph are the value.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

JAVA_PACK = LanguagePack(
    language="java",
    lang_slug="java",
    grammar="java",
    extensions=(".java",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,  # class + enum + record
            "def.interface": NodeKind.INTERFACE,
            "def.function": NodeKind.FUNCTION,  # method + constructor (promoted)
        }
    ),
    namespace_sep=".",  # `import com.foo.Bar` -> FQN resolution
)
