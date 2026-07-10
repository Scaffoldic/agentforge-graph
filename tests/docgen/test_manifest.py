"""feat-016 chunk 1: the generated-docs sidecar manifest."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.docgen import (
    DOC_LANG_VERSION,
    STATUS_ACCEPTED,
    STATUS_DRAFT,
    DocArtifact,
    DocType,
    Footnote,
    Manifest,
    SymbolRef,
    content_sha,
)


def _artifact(path: str, status: str = STATUS_DRAFT) -> DocArtifact:
    ref = SymbolRef(id="scip:s1", kind=NodeKind.CLASS, name="Repo", path="a.py", span=(1, 9))
    return DocArtifact(
        type=DocType.ARCHITECTURE,
        path=path,
        status=status,
        synced_commit="abc123",
        doc_lang_version=DOC_LANG_VERSION,
        source_ids=("scip:s1", "scip:s2"),
        footnotes=(Footnote(marker="f1", ref=ref),),
        content_sha=content_sha("hello"),
    )


def test_content_sha_stable() -> None:
    assert content_sha("hello") == content_sha("hello")
    assert content_sha("hello") != content_sha("world")


def test_upsert_get_all(tmp_path: Path) -> None:
    m = Manifest(tmp_path)
    assert m.all() == []
    a = _artifact("docs/_generated/architecture.md")
    m.upsert(a)
    assert m.get(a.path) == a
    assert [x.path for x in m.all()] == [a.path]


def test_persist_and_reload_roundtrip(tmp_path: Path) -> None:
    m = Manifest(tmp_path)
    a = _artifact("docs/_generated/architecture.md")
    m.upsert(a)
    # a fresh Manifest reads the same bytes back, fully typed
    m2 = Manifest(tmp_path)
    got = m2.get(a.path)
    assert got is not None
    assert got.type is DocType.ARCHITECTURE
    assert got.source_ids == ("scip:s1", "scip:s2")
    assert got.footnotes[0].marker == "f1"
    assert got.footnotes[0].ref.kind is NodeKind.CLASS
    assert got.footnotes[0].ref.span == (1, 9)
    assert got.content_sha == content_sha("hello")


def test_manifest_file_shape(tmp_path: Path) -> None:
    m = Manifest(tmp_path)
    m.upsert(_artifact("docs/_generated/architecture.md"))
    data = json.loads((tmp_path / ".ckg-docs.json").read_text())
    assert data["version"] == 1
    rec = data["docs"]["docs/_generated/architecture.md"]
    assert "stale" not in rec  # computed, never serialized
    assert rec["status"] == STATUS_DRAFT


def test_remove(tmp_path: Path) -> None:
    m = Manifest(tmp_path)
    a = _artifact("docs/_generated/x.md")
    m.upsert(a)
    m.remove(a.path)
    assert m.get(a.path) is None
    m.remove("nonexistent")  # no-op, no raise


def test_promote_flips_status(tmp_path: Path) -> None:
    m = Manifest(tmp_path)
    a = _artifact("docs/_generated/x.md", status=STATUS_DRAFT)
    m.upsert(a)
    promoted = m.promote(a.path)
    assert promoted.status == STATUS_ACCEPTED and promoted.accepted
    # persisted, and everything else preserved
    assert Manifest(tmp_path).get(a.path).status == STATUS_ACCEPTED  # type: ignore[union-attr]
    assert promoted.source_ids == a.source_ids
    # idempotent
    assert m.promote(a.path).status == STATUS_ACCEPTED
