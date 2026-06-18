"""``CommitIngestor`` — turn meaningful git commit messages into graph facts
(feat-010 follow-up).

A commit whose subject is a *conventional commit* (``feat:`` / ``fix:`` / …) or
carries an *issue reference* (``#123`` / ``PROJ-45``) is high-signal: it records
*why* a change was made. We ingest the subjects of the last ``limit`` such commits
as ``DocChunk``s that ``DESCRIBES`` the in-repo files they touched — so "why did
the retry logic change?" can reach the commit and the code it touched.

Git is read via ``git log`` (subprocess; no ``agentforge`` import — the knowledge
package stays deterministic, ADR-0001). Commit chunks are keyed by sha and added
idempotently (a re-index skips shas already present); they are immutable, so there
is no per-file GC.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)

_ALL = 10_000_000
_DOC_LANG = "doc"
_COMMITS_PATH = "<commits>"  # synthetic SymbolID path namespace for commit chunks
_RS = "\x1e"  # record separator between commits
_US = "\x1f"  # field separator within a commit's header line

# conventional commit: `type(scope)?!: summary`
_CONVENTIONAL = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert)(\([^)]*\))?!?:",
    re.IGNORECASE,
)
# an issue reference: `#123` or `PROJ-45`
_ISSUE_REF = re.compile(r"(#\d+|\b[A-Z][A-Z0-9]+-\d+\b)")


def _qualifies(subject: str) -> bool:
    return bool(_CONVENTIONAL.match(subject.strip()) or _ISSUE_REF.search(subject))


class CommitIngestor:
    def __init__(self, repo: str, root: str | Path, commit: str = "", limit: int = 50) -> None:
        self.repo = repo
        self.root = str(root)
        self.commit = commit
        self.limit = max(1, limit)

    async def ingest(self, store: GraphStore) -> int:
        commits = self._git_log()
        if not commits:
            return 0
        path_index = await self._path_index(store)
        existing = await self._existing_shas(store)
        prov = Provenance.parsed("commit-ingestor", self.commit)
        facts: list[Node | Edge] = []
        count = 0
        for sha, ts, author, subject, files in commits:
            if sha in existing or not _qualifies(subject):
                continue
            targets = [path_index[f] for f in files if f in path_index]
            if not targets:  # touched no in-repo code → nothing to describe
                continue
            chunk_id = SymbolID.for_symbol(
                _DOC_LANG, self.repo, _COMMITS_PATH, f"commit({sha[:12]})."
            )
            facts.append(
                Node(
                    id=chunk_id,
                    kind=NodeKind.DOC_CHUNK,
                    name=subject[:80],
                    attrs={
                        "path": _COMMITS_PATH,
                        "heading": subject[:80],
                        "text": subject,
                        "doc_source": "commit",
                        "commit": sha,
                        "author": author,
                        "ts": ts,
                        "content_hash": hashlib.sha256(f"{sha}:{subject}".encode()).hexdigest(),
                    },
                    provenance=prov,
                )
            )
            for target in sorted(set(targets)):
                facts.append(
                    Edge(src=chunk_id, dst=target, kind=EdgeKind.DESCRIBES, provenance=prov)
                )
            count += 1
        if facts:
            await store.add(facts)
        return count

    async def _path_index(self, store: GraphStore) -> dict[str, str]:
        return {
            SymbolID.parse(n.id).path: n.id
            for n in (await store.query(GraphQuery(kinds=[NodeKind.FILE], limit=_ALL))).nodes
        }

    async def _existing_shas(self, store: GraphStore) -> set[str]:
        nodes = (await store.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=_ALL))).nodes
        return {
            str(n.attrs.get("commit", "")) for n in nodes if n.attrs.get("doc_source") == "commit"
        }

    def _git_log(self) -> list[tuple[str, int, str, str, list[str]]]:
        """Last ``limit`` non-merge commits as (sha, author_ts, author, subject,
        touched files). Subject-only keeps the ``--name-only`` parse unambiguous;
        full-body ingestion is a refinement."""
        try:
            out = subprocess.run(
                [
                    "git",
                    "-C",
                    self.root,
                    "log",
                    f"-n{self.limit}",
                    "--no-merges",
                    "--no-color",
                    "--name-only",
                    f"--format={_RS}%H{_US}%ct{_US}%an{_US}%s",
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return []
        commits: list[tuple[str, int, str, str, list[str]]] = []
        for block in out.stdout.split(_RS):
            block = block.strip("\n")
            if not block:
                continue
            head, _, rest = block.partition("\n")
            parts = head.split(_US)
            if len(parts) < 4:
                continue
            sha, ts_s, author, subject = parts[0], parts[1], parts[2], parts[3]
            files = [ln for ln in rest.splitlines() if ln.strip()]
            commits.append((sha, int(ts_s) if ts_s.isdigit() else 0, author, subject, files))
        return commits
