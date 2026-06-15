"""The PHP language pack (Tier A — structure + namespace/FQN import resolution).

PHP is the first namespace/FQN-based pack: a file declares one `namespace`, and
`use App\\Foo\\Bar` resolves to the file declaring class `Bar` in namespace
`App\\Foo` (PSR-4 maps namespaces to dirs). Extracts class/interface/trait/enum
(→Class/Interface), functions, methods, and constants. Method/static calls
(`$x->m()`, `C::m()`) stay unresolved (member access, ADR-0004).
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

PHP_PACK = LanguagePack(
    language="php",
    lang_slug="php",
    grammar="php",
    extensions=(".php",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,  # class + trait + enum
            "def.interface": NodeKind.INTERFACE,
            "def.function": NodeKind.FUNCTION,  # function + method (promoted)
            "def.variable": NodeKind.VARIABLE,  # const
        }
    ),
    namespace_sep="\\",  # `use App\Foo\Bar` -> FQN resolution
)
