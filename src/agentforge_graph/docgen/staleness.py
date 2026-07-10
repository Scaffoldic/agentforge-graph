"""Staleness join for generated docs (feat-016) — one mechanism, reused.

Generated docs are a :class:`DirtySet` consumer (``"docs"``), exactly like
``embeddings`` / ``patterns`` / ``summaries``. Indexing already fans every changed
symbol id to all consumers; this module holds the *pure* join between a manifest
doc's ``source_ids`` and the ``"docs"`` dirty cursor. The async drain / regenerate
/ ``mark_clean`` loop lives in the generator (it mirrors ``CodeGraph.summarize``).
"""

from __future__ import annotations

from collections.abc import Iterable

from .types import DocArtifact

#: The ``DirtySet`` consumer name for generated docs (added to
#: ``DirtySet.DEFAULT_CONSUMERS``).
DOCS_CONSUMER = "docs"


def is_stale(artifact: DocArtifact, dirty: set[str], head_commit: str) -> bool:
    """A doc is stale when a source symbol was dirtied, or the index moved past
    the commit it was generated from. (A ``doc_lang_version`` bump is folded in by
    the caller, which knows the current version.)"""
    if dirty and any(sid in dirty for sid in artifact.source_ids):
        return True
    return bool(head_commit and artifact.synced_commit and artifact.synced_commit != head_commit)


def stale_docs(artifacts: Iterable[DocArtifact], dirty: Iterable[str]) -> list[DocArtifact]:
    """The docs whose ``source_ids`` intersect the dirty set — the regeneration
    work-list for ``ckg docs update``."""
    dirty_set = set(dirty)
    if not dirty_set:
        return []
    return [a for a in artifacts if any(sid in dirty_set for sid in a.source_ids)]
