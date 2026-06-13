"""The ``FrameworkPack`` ABC + ``FrameworkFacts`` (feat-011).

A framework pack rides feat-002's extraction: given a parsed file it emits
framework nodes/edges (``Route``/``DataModel``/``Service`` + ``HANDLED_BY``/…)
attached to the symbols the *language* pack already produced (same SymbolID
scheme). The facts are merged into the file's ``FileSubgraph`` (pipeline), so
they inherit feat-004 incrementality for free — file-owned, ``parsed``
provenance, never touched by the resolver's ``clear_resolved``.

Detection is declarative: a pack lists the dependency names and import markers
that mean "this repo uses me"; ``frameworks.detect`` does the scanning. Zero
``agentforge`` imports (ADR-0001).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

from agentforge_graph.core import Edge, GraphStore, Node, SourceFile


class FrameworkFacts(BaseModel):
    """What a pack derived from one file. ``unresolved`` counts registrations
    the pack recognised but could not extract statically (dynamic paths,
    class-based handlers at MVP) — surfaced in the IndexReport, never dropped
    silently."""

    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    unresolved: int = 0


class FrameworkPack(ABC):
    """A framework's extraction rules over one language's parse trees."""

    name: str = ""  # "fastapi"
    language: str = ""  # the language pack this rides ("python")
    language_slug: str = ""  # SymbolID slug of that language ("py")
    version: str = "1"  # bump on pattern changes (provenance + future --full)
    dep_names: tuple[str, ...] = ()  # manifest dependency names that imply this framework
    import_markers: tuple[str, ...] = ()  # source substrings that confirm use

    def detect(self, dep_names: set[str], source_sample: str) -> bool:
        """Active for this repo? A declared dependency, or an import marker in
        the sampled source. Override for bespoke detection."""
        if dep_names.intersection(self.dep_names):
            return True
        return any(marker in source_sample for marker in self.import_markers)

    @abstractmethod
    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        """Pass-1, file-isolated: emit framework nodes/edges for ``file``."""

    def resolve(self, store: GraphStore) -> list[Edge]:
        """Optional pass-2 cross-file stitching (router prefixes, string view
        refs). MVP packs return ``[]``."""
        return []

    def coupled_files(self, path: str) -> bool:
        """True for files whose change forces a framework re-resolve (e.g.
        ``urls.py``). MVP: no pass-2, so always False."""
        return False
