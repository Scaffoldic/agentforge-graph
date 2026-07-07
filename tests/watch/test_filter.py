"""feat-014: WatchFilter classifies paths the same way the indexer would ingest,
plus git metadata for on-commit."""

from __future__ import annotations

from agentforge_graph.ingest.packs import builtin_registry
from agentforge_graph.ingest.watch import EventKind
from agentforge_graph.ingest.watch.filter import WatchFilter


def _f(extra: list[str] | None = None) -> WatchFilter:
    return WatchFilter(builtin_registry(), extra_ignore=extra)


def test_source_file_is_a_file_event() -> None:
    ev = _f().classify("pkg/mod.py")
    assert ev is not None and ev.kind is EventKind.FILE


def test_git_head_and_refs_are_git_events() -> None:
    f = _f()
    assert f.classify(".git/HEAD").kind is EventKind.GIT  # type: ignore[union-attr]
    assert f.classify(".git/refs/heads/main").kind is EventKind.GIT  # type: ignore[union-attr]
    assert f.classify(".git/packed-refs").kind is EventKind.GIT  # type: ignore[union-attr]


def test_other_git_churn_ignored() -> None:
    assert _f().classify(".git/objects/ab/cdef") is None
    assert _f().classify(".git/index") is None


def test_non_source_ignored() -> None:
    assert _f().classify("README.md") is None  # not an indexed language
    assert _f().classify("data.bin") is None


def test_default_excludes_ignored() -> None:
    f = _f()
    assert f.classify("node_modules/x/y.py") is None
    assert f.classify(".venv/lib/z.py") is None
    assert f.classify(".ckg/meta.json") is None


def test_extra_ignore_globs_applied() -> None:
    f = _f(extra=["**/generated/**"])
    assert f.classify("app/generated/models.py") is None
    assert f.classify("app/real/models.py") is not None


def test_keep_is_classify_truthiness() -> None:
    f = _f()
    assert f.keep("pkg/mod.py") is True
    assert f.keep(".git/objects/aa") is False


def test_relative_outside_root_is_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    f = _f()
    assert f.relative(tmp_path, "/somewhere/else/x.py") is None
    assert f.relative(tmp_path, tmp_path / "a" / "b.py") == "a/b.py"
