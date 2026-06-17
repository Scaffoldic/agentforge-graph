"""History backfill (feat-009 chunk 4, ``ckg index --history N``).

Seeds the evolution log for code that predates temporal adoption by *replaying*
the last ``N`` commits oldest→newest through the **existing** incremental
pipeline against a **throwaway** graph store, feeding the real sidecar recorder
at each step. The HEAD index and the embeddings are never touched — backfill
writes lifecycle events only (design §4.6).

- File content at each historical commit is read from git (``git ls-tree`` +
  ``git show <commit>:<path>``) via :class:`GitBlobSource` — **no checkout
  churn**, the working tree is left alone.
- The per-step diff is ``git diff --name-status -M <parent> <commit>``.
- Churn/authorship mining is **skipped** during replay (it is a HEAD-time
  signal, mined by chunk 2; replaying it would clobber HEAD aggregates with
  stale values). Only ``OPENED``/``CLOSED`` are recorded.
- **Resumable**: the oldest covered commit is stored as ``backfilled_through``;
  a re-run whose requested range is already covered is a no-op. Events are
  idempotent (unique per symbol/commit/event), so a partial run re-runs safely.

The accuracy this buys: a symbol's earliest ``OPENED`` event becomes its true
introduction commit (within the backfilled horizon), so ``history().introduced``
is no longer window-bounded for pre-existing code.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
from collections.abc import Iterable, Iterator
from pathlib import Path, PurePosixPath

from pydantic import BaseModel

from agentforge_graph.core import SourceFile
from agentforge_graph.ingest.source import RepoSource
from agentforge_graph.store import Store

from .recorder import build_recorder, seed_symbols
from .store import TemporalStore

_FULL = -1  # `--history full` sentinel


class BackfillReport(BaseModel):
    ran: bool
    commits: int = 0
    events_before: int = 0
    events_after: int = 0
    backfilled_through: str = ""
    reason: str = ""

    @property
    def events_added(self) -> int:
        return max(self.events_after - self.events_before, 0)


def parse_history(value: str | int | None) -> int:
    """Normalise the ``--history`` argument: ``"full"`` → ``_FULL``; an int-ish
    → that many commits; ``None``/0 → 0 (no backfill)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    if value.strip().lower() == "full":
        return _FULL
    try:
        return max(int(value), 0)
    except ValueError:
        return 0


# --- a git-blob source: file content at a specific commit -----------------


class GitBlobSource(RepoSource):
    """A ``RepoSource`` that yields the indexable files of a specific *commit's*
    tree (read from git), not the working tree. ``restrict`` limits the read to
    a known path set (an incremental step only needs its touched files), so
    per-step cost is bounded — the working tree is never touched."""

    def __init__(
        self,
        root: str | Path,
        commit: str,
        *,
        exclude: list[str],
        include: list[str] | None = None,
        max_file_kb: int = 512,
        restrict: set[str] | None = None,
    ) -> None:
        super().__init__(root, include=include, exclude=exclude, max_file_kb=max_file_kb)
        self.commit = commit
        self._restrict = restrict

    def iter_files(self, registry: object) -> Iterator[SourceFile]:
        self.skipped = []
        for rel in self._tree_paths():
            if self._restrict is not None and rel not in self._restrict:
                continue
            if self._is_excluded(rel) or not self._is_included(rel):
                continue
            pack = registry.for_extension(PurePosixPath(rel).suffix)  # type: ignore[attr-defined]
            if pack is None:
                continue
            raw = self._blob(rel)
            if raw is None:
                continue
            if len(raw) > self.max_file_kb * 1024:
                self.skipped.append(f"{rel} (> {self.max_file_kb}KB)")
                continue
            yield SourceFile(
                path=rel,
                text=raw.decode("utf-8", errors="replace"),
                language=pack.lang_slug,
                content_hash=hashlib.sha256(raw).hexdigest(),
            )

    def _tree_paths(self) -> list[str]:
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "ls-tree", "-r", "--name-only", self.commit],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        return [p for p in out.stdout.splitlines() if p]

    def _blob(self, rel: str) -> bytes | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(self.root), "show", f"{self.commit}:{rel}"],
                capture_output=True,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return out.stdout


# --- a recorder that records lifecycle but skips churn --------------------


class _LifecycleOnly:
    """Wraps the real recorder; forwards open/close/flush but no-ops
    ``record_churn`` so replay never clobbers HEAD churn aggregates."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def open(self, symbol_ids: Iterable[str], at: str, ts: int) -> None:
        self._inner.open(symbol_ids, at, ts)  # type: ignore[attr-defined]

    def close(self, symbol_ids: Iterable[str], at: str, ts: int) -> None:
        self._inner.close(symbol_ids, at, ts)  # type: ignore[attr-defined]

    async def record_churn(self, *args: object, **kwargs: object) -> None:
        return None

    async def flush(self) -> None:
        await self._inner.flush()  # type: ignore[attr-defined]


# --- git helpers ----------------------------------------------------------


def _git(root: str | Path, *args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout


def _commit_list(root: str | Path, history: int) -> list[str]:
    """The commits to replay, oldest→newest. ``history == _FULL`` walks to the
    root; ``N`` takes the last ``N+1`` (a baseline + ``N`` diff steps)."""
    args = ["rev-list", "--reverse"]
    if history != _FULL:
        args += ["-n", str(history + 1)]
    args.append("HEAD")
    out = _git(root, *args)
    return [c for c in out.splitlines() if c] if out else []


def _commit_ts(root: str | Path, commit: str) -> int:
    out = _git(root, "show", "-s", "--format=%ct", commit)
    try:
        return int(out.strip()) if out else 0
    except ValueError:
        return 0


def _is_ancestor(root: str | Path, a: str, b: str) -> bool:
    """True if commit ``a`` is an ancestor of (or equal to) ``b``."""
    try:
        return (
            subprocess.run(
                ["git", "-C", str(root), "merge-base", "--is-ancestor", a, b],
                capture_output=True,
            ).returncode
            == 0
        )
    except (subprocess.SubprocessError, OSError):
        return False


def _changeset(root: str | Path, parent: str, commit: str, registry: object) -> object:
    """A feat-004 ``ChangeSet`` from ``git diff --name-status -M`` between two
    commits, restricted to indexable files."""
    from agentforge_graph.ingest.incremental import ChangeSet

    out = _git(root, "diff", "--name-status", "-M", parent, commit)
    added: list[str] = []
    modified: list[str] = []
    deleted: list[str] = []
    renamed: list[tuple[str, str]] = []

    def indexable(p: str) -> bool:
        return registry.for_extension(PurePosixPath(p).suffix) is not None  # type: ignore[attr-defined]

    for line in (out or "").splitlines():
        parts = line.split("\t")
        code = parts[0]
        if code.startswith("R") and len(parts) == 3:
            old, new = parts[1], parts[2]
            if indexable(old) or indexable(new):
                renamed.append((old, new))
        elif len(parts) == 2 and indexable(parts[1]):
            path = parts[1]
            if code.startswith("A"):
                added.append(path)
            elif code.startswith("M"):
                modified.append(path)
            elif code.startswith("D"):
                deleted.append(path)
    return ChangeSet(
        added=sorted(added),
        modified=sorted(modified),
        deleted=sorted(deleted),
        renamed=renamed,
    )


async def _open_temp_store(tmp: Path) -> Store:
    """An embedded (kuzu + lance) throwaway store, regardless of the real
    config's backend — backfill replays locally and discards it."""
    from agentforge_graph.config import StoreConfig
    from agentforge_graph.store.registry import graph_driver, vector_driver

    graph = await graph_driver("kuzu").open(tmp / "graph.kuzu")
    vectors = await vector_driver("lancedb").open(tmp / "vectors.lance")
    return Store(graph, vectors, StoreConfig())


async def run_backfill(
    repo_path: str | Path,
    config: str | Path | None,
    history: int,
    *,
    languages: str | list[str] | None = None,
) -> BackfillReport:
    """Replay ``history`` commits into the evolution log. See the module
    docstring for the model; returns a report (``ran=False`` with a reason when
    skipped)."""
    from agentforge_graph.config import IngestConfig, StoreConfig, TemporalConfig
    from agentforge_graph.ingest.codegraph import _registry_for
    from agentforge_graph.ingest.incremental import IncrementalIndexer
    from agentforge_graph.ingest.pipeline import IngestPipeline

    if history == 0:
        return BackfillReport(ran=False, reason="history=0 (nothing to backfill)")
    if not TemporalConfig.load(config).enabled:
        return BackfillReport(ran=False, reason="temporal disabled")

    commits = _commit_list(repo_path, history)
    if len(commits) < 2:  # need a baseline + ≥1 step
        return BackfillReport(ran=False, reason="not a git repo or too few commits")

    root = Path(repo_path) / StoreConfig.load(config).path
    tstore = TemporalStore.open(root)
    target_oldest = commits[0]
    cursor = await tstore.get_meta("backfilled_through")
    if cursor and _is_ancestor(repo_path, cursor, target_oldest):
        return BackfillReport(ran=False, reason="already backfilled", backfilled_through=cursor)

    ingest = IngestConfig.load(config)
    registry = _registry_for(languages if languages is not None else ingest.languages)
    repo = Path(repo_path).resolve().name
    exclude, max_kb = ingest.exclude, ingest.max_file_kb

    recorder = build_recorder(str(root))
    lifecycle = _LifecycleOnly(recorder)
    events_before = await tstore.count_events()

    with tempfile.TemporaryDirectory() as tmpdir:
        store = await _open_temp_store(Path(tmpdir))
        try:
            c0 = commits[0]
            src0 = GitBlobSource(repo_path, c0, exclude=exclude, max_file_kb=max_kb)
            await IngestPipeline(repo=repo, commit=c0).run(src0, store.graph, registry)
            # OPENED for everything alive at the baseline; repo_root="" → no churn
            await seed_symbols(store.graph, recorder, c0, _commit_ts(repo_path, c0))

            for prev, cur in zip(commits, commits[1:], strict=False):
                changes = _changeset(repo_path, prev, cur, registry)
                if changes.is_empty():  # type: ignore[attr-defined]
                    continue
                touched = set(changes.touched_paths())  # type: ignore[attr-defined]
                src = GitBlobSource(
                    repo_path, cur, exclude=exclude, max_file_kb=max_kb, restrict=touched
                )
                indexer = IncrementalIndexer(
                    store,
                    src,
                    registry,
                    repo,
                    commit=cur,
                    dirty=None,
                    recorder=lifecycle,
                    commit_ts=_commit_ts(repo_path, cur),
                )
                await indexer.refresh(changes)  # type: ignore[arg-type]
        finally:
            await store.close()

    await tstore.set_meta("backfilled_through", target_oldest)
    return BackfillReport(
        ran=True,
        commits=len(commits),
        events_before=events_before,
        events_after=await tstore.count_events(),
        backfilled_through=target_oldest,
    )
