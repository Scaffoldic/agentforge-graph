"""Unit coverage for the feat-004 incremental pieces: IndexMeta, ChangeDetector
(content-hash diff + git rename refinement), DirtySet, and the CodeGraph
full|incremental decision + dirty-scoped embed."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentforge_graph.ingest import CodeGraph, PackRegistry
from agentforge_graph.ingest.incremental import (
    ChangeDetector,
    ChangeSet,
    DirtySet,
    IndexMeta,
    pack_fingerprint,
)
from agentforge_graph.ingest.incremental.meta import _META
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.ingest.source import RepoSource

REG = PackRegistry([PYTHON_PACK])


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


# ---- IndexMeta -------------------------------------------------------------


def test_meta_roundtrip_and_load_default(tmp_path: Path) -> None:
    assert IndexMeta.load(tmp_path).indexed_commit == ""  # missing file → default
    meta = IndexMeta(indexed_commit="abc", files={"a.py": "h1"})
    meta.save(tmp_path)
    again = IndexMeta.load(tmp_path)
    assert again.indexed_commit == "abc"
    assert again.files == {"a.py": "h1"}
    assert not (tmp_path / (_META + ".tmp")).exists()  # temp cleaned by atomic replace


def test_meta_upgrades_from_minimal(tmp_path: Path) -> None:
    # an old meta.json (only schema_version + indexed_commit) must load cleanly
    (tmp_path / _META).write_text('{"schema_version": 1, "indexed_commit": "old"}')
    meta = IndexMeta.load(tmp_path)
    assert meta.indexed_commit == "old"
    assert meta.files == {} and meta.pack_versions == {}
    assert meta.is_indexed() is True  # has a commit → counts as indexed


def test_meta_is_indexed_and_packs_changed(tmp_path: Path) -> None:
    assert IndexMeta().is_indexed() is False
    assert IndexMeta(files={"a.py": "h"}).is_indexed() is True
    fps = IndexMeta.fingerprints([PYTHON_PACK])
    meta = IndexMeta(pack_versions=fps)
    assert meta.packs_changed([PYTHON_PACK]) is False
    assert IndexMeta(pack_versions={"py": "stale"}).packs_changed([PYTHON_PACK]) is True
    assert IndexMeta().packs_changed([PYTHON_PACK]) is True  # never seen


def test_pack_fingerprint_changes_with_queries() -> None:
    base = pack_fingerprint(PYTHON_PACK)
    mutated = PYTHON_PACK.model_copy(
        update={"structure_queries": PYTHON_PACK.structure_queries + ";"}
    )
    assert pack_fingerprint(mutated) != base


# ---- ChangeDetector --------------------------------------------------------


async def test_detect_fallback_classifies(tmp_path: Path) -> None:
    _write(tmp_path, {"keep.py": "x = 1\n", "edit.py": "a = 1\n", "gone.py": "g = 1\n"})
    source = RepoSource(tmp_path)
    first = await ChangeDetector(tmp_path).detect(source, IndexMeta(), REG)
    # against an empty manifest everything is "added"
    assert set(first.changes.added) == {"keep.py", "edit.py", "gone.py"}

    meta = IndexMeta(files=first.file_hashes)
    (tmp_path / "edit.py").write_text("a = 2\n")  # modify
    (tmp_path / "gone.py").unlink()  # delete
    (tmp_path / "new.py").write_text("n = 1\n")  # add
    res = await ChangeDetector(tmp_path).detect(RepoSource(tmp_path), meta, REG)
    assert res.changes.added == ["new.py"]
    assert res.changes.modified == ["edit.py"]
    assert res.changes.deleted == ["gone.py"]
    assert res.changes.is_empty() is False


async def test_detect_git_rename_refinement(tmp_path: Path) -> None:
    _write(tmp_path, {"a.py": "def f():\n    return 1\n"})
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "init")
    head = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    base_files = {sf.path: sf.content_hash for sf in RepoSource(tmp_path).iter_files(REG)}

    # rename a.py -> b.py and commit (git records it as a rename)
    _git(tmp_path, "mv", "a.py", "b.py")
    _git(tmp_path, "commit", "-m", "rename")
    meta = IndexMeta(indexed_commit=head, files=base_files)
    res = await ChangeDetector(tmp_path).detect(RepoSource(tmp_path), meta, REG)
    assert ("a.py", "b.py") in res.changes.renamed
    assert "a.py" not in res.changes.deleted and "b.py" not in res.changes.added
    assert res.changes.removed_paths() == ["a.py"]
    assert res.changes.touched_paths() == ["b.py"]


def test_changeset_path_helpers() -> None:
    cs = ChangeSet(added=["a"], modified=["b"], deleted=["c"], renamed=[("d", "e")])
    assert cs.touched_paths() == ["a", "b", "e"]
    assert cs.removed_paths() == ["c", "d"]
    assert cs.changed_paths() == ["a", "b", "c", "d", "e"]


# ---- DirtySet --------------------------------------------------------------


async def test_dirty_add_dedupe_clean_persist(tmp_path: Path) -> None:
    ds = DirtySet(tmp_path, consumers=["embeddings", "summaries"])
    await ds.add(["s1", "s2", "s1"])  # dup ignored
    await ds.add(["s2", "s3"])
    assert await ds.dirty_for("embeddings") == ["s1", "s2", "s3"]
    assert await ds.dirty_for("summaries") == ["s1", "s2", "s3"]
    await ds.add([])  # no-op
    await ds.mark_clean("embeddings", ["s1", "s3"])
    assert await ds.dirty_for("embeddings") == ["s2"]
    # persisted across instances
    assert await DirtySet(tmp_path).dirty_for("embeddings") == ["s2"]
    assert await DirtySet(tmp_path, consumers=["summaries"]).dirty_for("summaries") == [
        "s1",
        "s2",
        "s3",
    ]


# ---- CodeGraph decision + dirty embed --------------------------------------


async def test_pack_change_forces_full(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "proj"
    _write(repo, {"m.py": "def f():\n    return 1\n"})
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()
    # corrupt the stored pack fingerprint → next index must rebuild fully
    from agentforge_graph.config import StoreConfig

    root = repo / StoreConfig.load(None).path
    meta = IndexMeta.load(root)
    meta.pack_versions = {"py": "STALE"}
    meta.save(root)
    assert meta.packs_changed([PYTHON_PACK]) is True
    cg2 = await CodeGraph.index(repo_path=repo)  # should not raise; full rebuild
    try:
        assert cg2.stats().files_indexed == 1
    finally:
        await cg2.close()


async def test_embed_only_dirty(tmp_path: Path) -> None:
    from agentforge_graph.config import StoreConfig
    from agentforge_graph.embed import FakeEmbedder

    repo = tmp_path / "proj"
    _write(repo, {"m.py": "def square(x):\n    return x * x\n", "app.py": "y = 1\n"})
    cg = await CodeGraph.index(repo_path=repo)
    await cg.embed(embedder=FakeEmbedder(dim=8))  # embed all first

    root = repo / StoreConfig.load(None).path
    ds = DirtySet(root)
    # seed the dirty set with a symbol in m.py (as a refresh would)
    from agentforge_graph.core import GraphQuery, NodeKind, SymbolID

    nodes = (await cg.store.graph.query(GraphQuery(limit=10_000_000))).nodes
    m_sym = next(
        n.id for n in nodes if n.kind is NodeKind.FUNCTION and SymbolID.parse(n.id).path == "m.py"
    )
    await ds.add([m_sym])
    report = await cg.embed(embedder=FakeEmbedder(dim=8), only_dirty=True)
    try:
        assert report.files == 1  # only m.py revisited
        assert await DirtySet(root).dirty_for("embeddings") == []  # drained
    finally:
        await cg.close()
