"""The Go language pack (Tier A — structure + directory-package import resolution).

Go differs from the file-level packs: a **package is a directory**, so every
``.go`` file in a dir shares one module key (``module_style="go"``). Import paths
are full module paths (``example.com/m/internal/bar``); the resolver suffix-matches
them to an in-repo package dir (it can't know the go.mod module prefix). Methods
are package-scoped (attached to a receiver type), captured here as ``Method`` but
file-owned — receiver→method ``CONTAINS`` linkage is a follow-up.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

GO_PACK = LanguagePack(
    language="go",
    lang_slug="go",
    grammar="go",
    extensions=(".go",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.function": NodeKind.FUNCTION,
            "def.method": NodeKind.METHOD,
            "def.class": NodeKind.CLASS,  # struct
            "def.interface": NodeKind.INTERFACE,
            "def.type": NodeKind.TYPE_ALIAS,  # defined types / aliases
            "def.variable": NodeKind.VARIABLE,  # package-level const/var
        }
    ),
    module_style="go",
)
