"""RepoSource: file discovery, excludes/includes, size limit, hashing."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.ingest import PackRegistry, RepoSource


def test_iter_yields_python_files(python_repo: Path, registry: PackRegistry) -> None:
    files = list(RepoSource(python_repo).iter_files(registry))
    assert {f.path for f in files} == {"mathutils.py", "shapes.py"}
    assert all(f.language == "py" for f in files)
    assert all(len(f.content_hash) == 64 for f in files)


def test_exclude_glob(python_repo: Path, registry: PackRegistry) -> None:
    src = RepoSource(python_repo, exclude=["**/shapes.py"])
    assert {f.path for f in src.iter_files(registry)} == {"mathutils.py"}


def test_include_glob(python_repo: Path, registry: PackRegistry) -> None:
    src = RepoSource(python_repo, include=["**/math*.py"])
    assert {f.path for f in src.iter_files(registry)} == {"mathutils.py"}


def test_max_file_kb_skips_and_records(python_repo: Path, registry: PackRegistry) -> None:
    src = RepoSource(python_repo, max_file_kb=0)  # everything is "too big"
    assert list(src.iter_files(registry)) == []
    assert len(src.skipped) == 2
    assert all("KB" in s for s in src.skipped)


def test_unknown_extension_skipped(tmp_path: Path, registry: PackRegistry) -> None:
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "b.rs").write_text("fn main() {}\n")
    src = RepoSource(tmp_path)
    assert {f.path for f in src.iter_files(registry)} == {"a.py"}


def test_content_hash_matches_bytes(python_repo: Path, registry: PackRegistry) -> None:
    f = next(f for f in RepoSource(python_repo).iter_files(registry) if f.path == "mathutils.py")
    raw = (python_repo / "mathutils.py").read_bytes()
    assert f.content_hash == hashlib.sha256(raw).hexdigest()


def test_nested_directories_use_posix_paths(tmp_path: Path, registry: PackRegistry) -> None:
    pkg = tmp_path / "pkg" / "sub"
    pkg.mkdir(parents=True)
    (pkg / "mod.py").write_text("y = 2\n")
    files = list(RepoSource(tmp_path).iter_files(registry))
    assert [f.path for f in files] == ["pkg/sub/mod.py"]
