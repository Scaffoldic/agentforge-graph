"""``RepoSource`` — walk a repository and yield one ``SourceFile`` per
indexable file. The pipeline's only filesystem boundary.

Files with no matching pack are skipped silently (not our languages); files
excluded by glob or over the size limit are skipped *and recorded* in
``skipped`` so the count surfaces in the IndexReport — never a silent gap.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from agentforge_graph.config import DEFAULT_EXCLUDES
from agentforge_graph.core import SourceFile

from .pack import PackRegistry


class RepoSource:
    def __init__(
        self,
        root: str | Path,
        include: list[str] | None = None,
        exclude: list[str] | None = None,
        max_file_kb: int = 512,
    ) -> None:
        self.root = Path(root)
        self.include = include
        self.exclude = list(DEFAULT_EXCLUDES) if exclude is None else exclude
        self.max_file_kb = max_file_kb
        self.skipped: list[str] = []

    def iter_files(self, registry: PackRegistry) -> Iterator[SourceFile]:
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(self.root).as_posix()
            if self._is_excluded(rel) or not self._is_included(rel):
                continue
            pack = registry.for_extension(path.suffix)
            if pack is None:  # not a language we index
                continue
            if path.stat().st_size > self.max_file_kb * 1024:
                self.skipped.append(f"{rel} (> {self.max_file_kb}KB)")
                continue
            raw = path.read_bytes()
            yield SourceFile(
                path=rel,
                text=raw.decode("utf-8", errors="replace"),
                language=pack.lang_slug,
                content_hash=hashlib.sha256(raw).hexdigest(),
            )

    def _is_excluded(self, rel: str) -> bool:
        return any(PurePosixPath(rel).full_match(glob) for glob in self.exclude)

    def _is_included(self, rel: str) -> bool:
        if self.include is None:
            return True
        return any(PurePosixPath(rel).full_match(glob) for glob in self.include)
