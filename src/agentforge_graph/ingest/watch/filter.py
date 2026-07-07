"""feat-014: classify a changed path into a watch :class:`Event` (or ignore it).

The single source of truth for "what does watch react to". It reacts to exactly
what the indexer would ingest — reusing the same ``full_match`` glob matching
:class:`~agentforge_graph.ingest.source.RepoSource` uses — plus git metadata
(``HEAD`` / refs) so the ``on-commit`` trigger can see commits and branch
switches. Everything else (``.git`` internals, ``node_modules``, ``.venv``, the
``.ckg`` index itself, non-source files) is ignored, so ignored churn never even
wakes the loop.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from agentforge_graph.config import DEFAULT_EXCLUDES
from agentforge_graph.ingest.pack import PackRegistry

from .policy import Event, EventKind

# git metadata whose change means "the commit/branch moved": HEAD itself, any
# ref under refs/, and the packed-refs file (branch switches / commits touch one).
_GIT_REF_HINTS = ("HEAD", "packed-refs")


class WatchFilter:
    def __init__(
        self,
        registry: PackRegistry,
        *,
        excludes: list[str] | None = None,
        extra_ignore: list[str] | None = None,
    ) -> None:
        self.registry = registry
        base = list(DEFAULT_EXCLUDES) if excludes is None else list(excludes)
        self.excludes = base + list(extra_ignore or [])

    def classify(self, rel: str) -> Event | None:
        """Map a repo-relative posix path to the event it should raise, or None to
        ignore it. Git metadata is checked *before* excludes (``.git`` is excluded
        for ingestion but its HEAD/refs are exactly what ``on-commit`` needs)."""
        parts = PurePosixPath(rel).parts
        if parts and parts[0] == ".git":
            if _is_git_ref(parts):
                return Event(EventKind.GIT, rel)
            return None
        if self._excluded(rel):
            return None
        if self.registry.for_extension(PurePosixPath(rel).suffix) is None:
            return None
        return Event(EventKind.FILE, rel)

    def keep(self, rel: str) -> bool:
        """watchfiles filter form: keep (wake the loop) iff the path classifies."""
        return self.classify(rel) is not None

    def relative(self, root: str | Path, path: str | Path) -> str | None:
        """Repo-relative posix form of an absolute event path, or None if outside
        the repo (watchfiles only reports inside-root paths, but be defensive)."""
        try:
            return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            return None

    def _excluded(self, rel: str) -> bool:
        return any(PurePosixPath(rel).full_match(glob) for glob in self.excludes)


def _is_git_ref(parts: tuple[str, ...]) -> bool:
    # parts[0] == ".git"
    if len(parts) >= 2 and parts[1] in _GIT_REF_HINTS:
        return True
    return len(parts) >= 2 and parts[1] == "refs"
