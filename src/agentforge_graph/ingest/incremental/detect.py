"""``ChangeDetector`` — diff the working tree against the indexed manifest.

The **content hash is the source of truth**: we walk the working tree once,
hash every indexable file, and diff that against ``IndexMeta.files``. This is
correct regardless of git state (dirty working tree, shallow clone, detached
HEAD, rebase) and naturally catches uncommitted edits — the common case for an
agent mid-flight. Git is then consulted *best-effort* only to promote a
matching delete+add pair into a rename (nicer reporting); if git disagrees or
is absent, the hash diff stands and a move simply reads as delete + add
(accepted at 0.2, spec §3).
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from pydantic import BaseModel, Field

from agentforge_graph.ingest.pack import PackRegistry
from agentforge_graph.ingest.source import RepoSource

from .meta import IndexMeta


class ChangeSet(BaseModel):
    """Files that changed since the last index, classified."""

    added: list[str] = Field(default_factory=list)
    modified: list[str] = Field(default_factory=list)
    deleted: list[str] = Field(default_factory=list)
    renamed: list[tuple[str, str]] = Field(default_factory=list)  # (old, new)

    def is_empty(self) -> bool:
        return not (self.added or self.modified or self.deleted or self.renamed)

    def touched_paths(self) -> list[str]:
        """Files to (re)extract: added, modified, and the new side of renames."""
        return sorted({*self.added, *self.modified, *(new for _, new in self.renamed)})

    def removed_paths(self) -> list[str]:
        """Files to delete from the store: deleted, and the old side of renames."""
        return sorted({*self.deleted, *(old for old, _ in self.renamed)})

    def changed_paths(self) -> list[str]:
        """Every path the diff touches on either side — the re-resolve seed."""
        return sorted({*self.touched_paths(), *self.removed_paths()})


class DetectResult(BaseModel):
    changes: ChangeSet
    file_hashes: dict[str, str]  # the fresh, full path -> content_hash manifest


class ChangeDetector:
    def __init__(self, repo_path: str | Path = ".") -> None:
        self.repo_path = repo_path

    async def detect(
        self, source: RepoSource, meta: IndexMeta, registry: PackRegistry
    ) -> DetectResult:
        current = await asyncio.to_thread(self._current_hashes, source, registry)
        prior = meta.files
        added = [p for p in current if p not in prior]
        modified = [p for p in current if p in prior and current[p] != prior[p]]
        deleted = [p for p in prior if p not in current]
        changes = ChangeSet(added=sorted(added), modified=sorted(modified), deleted=sorted(deleted))
        self._refine_renames(changes, meta.indexed_commit)
        return DetectResult(changes=changes, file_hashes=current)

    @staticmethod
    def _current_hashes(source: RepoSource, registry: PackRegistry) -> dict[str, str]:
        return {sf.path: sf.content_hash for sf in source.iter_files(registry)}

    def _refine_renames(self, changes: ChangeSet, base_commit: str) -> None:
        """Best-effort: if git reports a committed rename old->new and our hash
        diff independently saw `old` deleted and `new` added, collapse the pair
        into a rename. Purely cosmetic — the indexer treats a rename as
        delete(old)+add(new) anyway (§3), so a miss here changes nothing."""
        if not base_commit:
            return
        added = set(changes.added)
        deleted = set(changes.deleted)
        for old, new in self._git_renames(base_commit):
            if old in deleted and new in added:
                changes.renamed.append((old, new))
                changes.deleted.remove(old)
                changes.added.remove(new)
                deleted.discard(old)
                added.discard(new)

    def _git_renames(self, base_commit: str) -> list[tuple[str, str]]:
        try:
            out = subprocess.run(
                [
                    "git",
                    "-C",
                    str(self.repo_path),
                    "diff",
                    "--name-status",
                    "-M",
                    "--diff-filter=R",
                    base_commit,
                    "HEAD",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        pairs: list[tuple[str, str]] = []
        for line in out.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) == 3 and parts[0].startswith("R"):
                pairs.append((parts[1], parts[2]))
        return pairs
