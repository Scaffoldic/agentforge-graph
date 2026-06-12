"""Language packs: everything language-specific about extraction, behind one
shape so the extractor (extractor.py) stays language-agnostic.

A pack pairs a tree-sitter grammar with two ``.scm`` query files and a small
rule set mapping capture names to node kinds. The capture-name vocabulary is
shared across packs (``def.class``, ``def.function``, ``def.method``,
``name``, ``import``, ``import.module``, ``call``, ``call.callee``) so an
edge kind means the same thing in every language.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from agentforge_graph.core import NodeKind


class DescriptorRules(BaseModel):
    """Maps a structure-query capture name (e.g. ``def.class``) to the node
    kind it produces. Capture names prefixed ``def.`` mark definitions that
    nest descriptors and own a ``CONTAINS`` subtree."""

    kinds: dict[str, NodeKind] = Field(default_factory=dict)

    def kind_for(self, capture: str) -> NodeKind | None:
        return self.kinds.get(capture)


class LanguagePack(BaseModel):
    """A language's grammar + queries + descriptor rules."""

    language: str  # human name, e.g. "python"
    lang_slug: str  # symbol-ID language slug, e.g. "py"
    grammar: str  # tree-sitter-language-pack grammar name
    extensions: tuple[str, ...]  # file extensions, e.g. (".py",)
    structure_queries: str  # .scm: defs/classes/imports
    reference_queries: str  # .scm: calls/attribute refs
    descriptor_rules: DescriptorRules = Field(default_factory=DescriptorRules)

    def module_path(self, repo_relative_path: str) -> str:
        """Map a file path to this language's import module name. Default is
        Python-style dotted modules (``a/b/c.py`` -> ``a.b.c``, dropping a
        trailing ``__init__``); other packs override."""
        parts = repo_relative_path.removesuffix(f".{self.extensions[0].lstrip('.')}")
        segs = [s for s in parts.split("/") if s]
        if segs and segs[-1] == "__init__":
            segs = segs[:-1]
        return ".".join(segs)


class PackRegistry:
    """Resolves a file to the pack that handles it, by extension."""

    def __init__(self, packs: list[LanguagePack]) -> None:
        self._packs = list(packs)
        self._by_ext: dict[str, LanguagePack] = {}
        self._by_lang: dict[str, LanguagePack] = {}
        self._by_slug: dict[str, LanguagePack] = {}
        for pack in packs:
            self._by_lang[pack.language] = pack
            self._by_slug[pack.lang_slug] = pack
            for ext in pack.extensions:
                self._by_ext[ext] = pack

    @property
    def packs(self) -> list[LanguagePack]:
        return list(self._packs)

    def for_extension(self, suffix: str) -> LanguagePack | None:
        return self._by_ext.get(suffix)

    def for_language(self, name: str) -> LanguagePack | None:
        return self._by_lang.get(name)

    def for_slug(self, slug: str) -> LanguagePack | None:
        return self._by_slug.get(slug)
