"""The Ruby language pack (Tier A — structure + require_relative resolution).

Ruby modules/classes nest methods; `require_relative "./x"` is path-based and
resolves in-repo (``module_style="relative"``), while `require "gem"` stays
external. Ruby also autoloads (Rails) and uses heavy metaprogramming, so the
import graph is sparser than in static languages — symbol extraction is the
primary value; receiver-qualified calls stay unresolved (ADR-0004).
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.ingest.pack import DescriptorRules, LanguagePack

_HERE = Path(__file__).parent

RUBY_PACK = LanguagePack(
    language="ruby",
    lang_slug="rb",
    grammar="ruby",
    extensions=(".rb",),
    structure_queries=(_HERE / "structure.scm").read_text(encoding="utf-8"),
    reference_queries=(_HERE / "references.scm").read_text(encoding="utf-8"),
    descriptor_rules=DescriptorRules(
        kinds={
            "def.class": NodeKind.CLASS,  # class + module
            "def.function": NodeKind.FUNCTION,  # def (promoted to Method in a class)
            "def.method": NodeKind.METHOD,  # def self.x
            "def.variable": NodeKind.VARIABLE,  # constant assignment
        }
    ),
    module_style="relative",  # require_relative paths are relative to the file
    relative_bare=True,  # `require_relative "thor/x"` (bare) is still file-relative
    wildcard_import=True,  # require_relative brings in all the file's top-level defs
)
