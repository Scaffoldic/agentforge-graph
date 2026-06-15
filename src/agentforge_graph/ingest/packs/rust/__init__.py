"""The Rust language pack (Tier A — structure + path-derived module resolution).

Rust's module path is implicit in the file layout (`src/a/b.rs` is module `a::b`),
so the pack derives each file's module from its path (`namespace_from_path`) and
resolves `use crate::a::b::Item` to the file declaring `Item` (FQN-style, sep
`::`, with `crate::` stripped). Extracts struct/enum/union/impl (→Class), trait
(→Interface), functions + methods, const/static (→Variable), type aliases. `impl`
blocks attach their methods to the type. Method/path calls stay unresolved
(ADR-0004); grouped/glob `use` is a follow-up.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

RUST_PACK = LanguagePack(
    language="rust",
    lang_slug="rs",
    grammar="rust",
    extensions=(".rs",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,  # struct + enum + union + impl
            "def.interface": NodeKind.INTERFACE,  # trait
            "def.function": NodeKind.FUNCTION,  # fn + trait method sig (promoted)
            "def.variable": NodeKind.VARIABLE,  # const + static
            "def.type": NodeKind.TYPE_ALIAS,
        }
    ),
    namespace_sep="::",
    namespace_from_path=True,  # module path is the file path, not a declaration
)
