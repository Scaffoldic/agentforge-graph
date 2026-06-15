"""Language packs: everything language-specific about extraction, behind one
shape so the extractor (extractor.py) stays language-agnostic.

A pack pairs a tree-sitter grammar with two ``.scm`` query files and a small
rule set mapping capture names to node kinds. The capture-name vocabulary is
shared across packs (``def.class``, ``def.function``, ``def.method``,
``name``, ``import``, ``import.module``, ``call``, ``call.callee``) so an
edge kind means the same thing in every language.
"""

from __future__ import annotations

import posixpath
from typing import Literal

from pydantic import BaseModel, Field

from agentforge_graph.core import NodeKind

_INIT_BASENAMES = ("__init__.py", "__init__.pyi")  # a file that *is* its package


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
    # How imports name modules: "dotted" (Python `a.b.c`), "relative" (TS/JS path
    # specifiers like `./util`), or "go" (a package is a *directory*; import paths
    # are full module paths the resolver suffix-matches to a repo dir). Drives
    # module_path + resolve_import.
    module_style: Literal["dotted", "relative", "go"] = "dotted"

    def _strip_ext(self, path: str) -> str:
        for ext in self.extensions:
            if path.endswith(ext):
                return path[: -len(ext)]
        return path

    def module_path(self, repo_relative_path: str) -> str:
        """The module key a file is imported as. ``dotted``: ``a/b/c.py`` ->
        ``a.b.c`` (drops a trailing ``__init__``). ``relative``: the
        extension-stripped path, ``a/b/c.ts`` -> ``a/b/c``. ``go``: a package is
        a directory, so the key is the file's *directory*, ``a/b/c.go`` ->
        ``a/b`` (every ``.go`` file in a dir shares one package key)."""
        no_ext = self._strip_ext(repo_relative_path)
        if self.module_style == "go":
            return posixpath.dirname(repo_relative_path)
        if self.module_style == "relative":
            return no_ext
        segs = [s for s in no_ext.split("/") if s]
        if segs and segs[-1] == "__init__":
            segs = segs[:-1]
        return ".".join(segs)

    def resolve_import(self, importer_path: str, raw_module: str, importer_module: str = "") -> str:
        """Map an import as written in ``importer_path`` to a module key
        comparable to ``module_path``.

        ``relative`` (TS/JS): a ``./``/``../`` specifier is resolved against the
        importer's directory; a bare specifier (``react``) stays as-is (external).

        ``dotted`` (Python): an absolute import (``a.b.c``) is identity; a
        **relative** import (leading dots, e.g. ``.utils`` / ``..pkg.mod`` / ``.``)
        is resolved against ``importer_module`` — the importer's own (source-root
        stripped) module key — to an absolute key (BUG-004). One leading dot is the
        importer's package; each extra dot ascends one level."""
        if self.module_style == "go":
            # A Go import is a full module path ("example.com/m/internal/bar").
            # We can't know the go.mod module prefix here, so return it as-is;
            # the resolver suffix-matches it against in-repo package dirs.
            return raw_module
        if self.module_style == "relative":
            target = self._strip_ext(raw_module)
            if target.startswith("./") or target.startswith("../"):
                base = posixpath.dirname(importer_path)
                return posixpath.normpath(posixpath.join(base, target))
            return target
        # dotted
        dots = len(raw_module) - len(raw_module.lstrip("."))
        if not dots:
            return raw_module  # absolute dotted import: identity
        remainder = raw_module[dots:]  # name after the dots: "utils", "pkg.mod", ""
        segs = [s for s in importer_module.split(".") if s]
        # a regular module file lives *in* its package; an __init__ file *is* it
        if posixpath.basename(importer_path) not in _INIT_BASENAMES and segs:
            segs = segs[:-1]
        up = dots - 1  # the first dot is the importer's package; extras ascend
        if up:
            segs = segs[:-up] if up <= len(segs) else []
        base = ".".join(segs)
        if remainder:
            return f"{base}.{remainder}" if base else remainder
        return base


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
