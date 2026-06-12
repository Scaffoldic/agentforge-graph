"""agentforge_graph.ingest — the tree-sitter ingestion pipeline (feat-002).

Parses a repo with tree-sitter (no build config — ADR-0002) into the
feat-001 graph and writes it through the feat-003 store. Two passes:
file-isolated *extract* then graph-only *resolve*. Imports nothing from
``agentforge`` (ADR-0001).
"""

from __future__ import annotations

from .extractor import TreeSitterExtractor
from .pack import DescriptorRules, LanguagePack, PackRegistry
from .source import RepoSource

__all__ = [
    "RepoSource",
    "LanguagePack",
    "DescriptorRules",
    "PackRegistry",
    "TreeSitterExtractor",
]
