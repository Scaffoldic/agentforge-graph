"""``FrameworkExtractor`` — run the active framework packs over one file
(feat-011). Selects packs by the file's language and merges their
``FrameworkFacts``. File-isolated and stateless, so it runs inside the same
worker thread as the language extractor (pipeline)."""

from __future__ import annotations

from agentforge_graph.core import SourceFile

from .base import FrameworkFacts, FrameworkPack


class FrameworkExtractor:
    def __init__(self, packs: list[FrameworkPack]) -> None:
        self._packs = list(packs)
        self._by_slug: dict[str, list[FrameworkPack]] = {}
        for pack in packs:
            self._by_slug.setdefault(pack.language_slug, []).append(pack)

    @property
    def active(self) -> bool:
        return bool(self._packs)

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        merged = FrameworkFacts()
        for pack in self._by_slug.get(file.language, []):
            facts = pack.extract(file, repo, commit)
            merged.nodes.extend(facts.nodes)
            merged.edges.extend(facts.edges)
            merged.unresolved += facts.unresolved
        return merged
