"""The C++ language pack (Tier B — structure + heuristic refs).

Tier B per the language scope: comprehensive symbol extraction (classes, structs,
enums, free functions, methods) + quoted `#include` resolution, but reference
resolution is heuristic — C++'s overloading, templates, and `obj.method()` /
`ns::fn()` member access keep most calls unresolved (ADR-0004). Quoted includes
(`#include "geo/shape.h"`) are resolved relative to the including file (a bare
path, like Ruby); `<system>` includes are skipped.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

CPP_PACK = LanguagePack(
    language="cpp",
    lang_slug="cpp",
    grammar="cpp",
    extensions=(".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx", ".h"),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,  # class + struct + enum
            "def.function": NodeKind.FUNCTION,  # free fn + method (promoted in a class)
        }
    ),
    module_style="relative",  # `#include "geo/shape.h"` resolved relative to the file
    relative_bare=True,  # includes have no leading `./`
)
