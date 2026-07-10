"""The generated-docs manifest — a sidecar record of every draft (feat-016).

Generated docs are markdown **files** under ``docgen.output_root`` (what a human
reviews and commits); their metadata — status, the commit they were synced from,
the symbols they ground on, and their verified footnotes — lives beside them in
``output_root/.ckg-docs.json``. This mirrors the ``.ckg/dirty.json`` side-file
pattern (feat-004): a status/promote update never rewrites the docs themselves.

The manifest is the source for ``ckg docs list`` / ``diff`` / ``promote`` and the
staleness join (a doc's ``source_ids`` vs the ``DirtySet("docs")`` cursor).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from agentforge_graph.core import NodeKind

from .types import (
    STATUS_ACCEPTED,
    DocArtifact,
    DocType,
    Footnote,
    SymbolRef,
)

_MANIFEST = ".ckg-docs.json"
_SCHEMA_VERSION = 1


def content_sha(text: str) -> str:
    """sha256 of a doc's bytes — lets ``list``/``diff`` detect a human edit since
    generation without storing a second copy."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- (de)serialization -------------------------------------------------------


def _ref_to_dict(ref: SymbolRef) -> dict[str, Any]:
    return {
        "id": ref.id,
        "kind": str(ref.kind),
        "name": ref.name,
        "path": ref.path,
        "span": list(ref.span) if ref.span is not None else None,
    }


def _ref_from_dict(d: dict[str, Any]) -> SymbolRef:
    span = d.get("span")
    return SymbolRef(
        id=d["id"],
        kind=NodeKind(d["kind"]),
        name=d["name"],
        path=d.get("path"),
        span=(span[0], span[1]) if span else None,
    )


def _artifact_to_record(a: DocArtifact) -> dict[str, Any]:
    # ``stale`` is computed, never persisted.
    return {
        "type": str(a.type),
        "status": a.status,
        "synced_commit": a.synced_commit,
        "doc_lang_version": a.doc_lang_version,
        "source_ids": list(a.source_ids),
        "scope": a.scope,
        "footnotes": [{"marker": f.marker, "ref": _ref_to_dict(f.ref)} for f in a.footnotes],
        "content_sha": a.content_sha,
    }


def _artifact_from_record(path: str, r: dict[str, Any]) -> DocArtifact:
    return DocArtifact(
        type=DocType(r["type"]),
        path=path,
        status=r["status"],
        synced_commit=r.get("synced_commit", ""),
        doc_lang_version=r.get("doc_lang_version", ""),
        source_ids=tuple(r.get("source_ids", [])),
        scope=r.get("scope"),
        footnotes=tuple(
            Footnote(marker=f["marker"], ref=_ref_from_dict(f["ref"]))
            for f in r.get("footnotes", [])
        ),
        content_sha=r.get("content_sha", ""),
    )


# --- the manifest ------------------------------------------------------------


class Manifest:
    """The ``output_root/.ckg-docs.json`` record, keyed by repo-relative doc path.

    Mutating ops persist immediately (like :class:`DirtySet`), so a crash never
    leaves the manifest out of sync with the files on disk."""

    def __init__(self, output_root: str | Path) -> None:
        self._root = Path(output_root)
        self._path = self._root / _MANIFEST
        self._docs: dict[str, DocArtifact] = self._load()

    def _load(self) -> dict[str, DocArtifact]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text())
        docs = data.get("docs", {}) if isinstance(data, dict) else {}
        return {p: _artifact_from_record(p, r) for p, r in docs.items()}

    def _save(self) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _SCHEMA_VERSION,
            "docs": {p: _artifact_to_record(a) for p, a in sorted(self._docs.items())},
        }
        tmp = self._path.with_name(_MANIFEST + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True))
        tmp.replace(self._path)

    def get(self, path: str) -> DocArtifact | None:
        return self._docs.get(path)

    def all(self) -> list[DocArtifact]:
        return [self._docs[p] for p in sorted(self._docs)]

    def upsert(self, artifact: DocArtifact) -> None:
        self._docs[artifact.path] = artifact
        self._save()

    def remove(self, path: str) -> None:
        if path in self._docs:
            del self._docs[path]
            self._save()

    def promote(self, path: str) -> DocArtifact:
        """Flip a draft to ``accepted`` (the human review gate). Idempotent for an
        already-accepted doc; ``KeyError`` if the doc is unknown."""
        current = self._docs[path]
        promoted = DocArtifact(
            type=current.type,
            path=current.path,
            status=STATUS_ACCEPTED,
            synced_commit=current.synced_commit,
            doc_lang_version=current.doc_lang_version,
            source_ids=current.source_ids,
            scope=current.scope,
            footnotes=current.footnotes,
            content_sha=current.content_sha,
        )
        self._docs[path] = promoted
        self._save()
        return promoted
