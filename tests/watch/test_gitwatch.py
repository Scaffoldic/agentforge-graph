"""feat-014: branch gating + branch reading."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.ingest.watch import branch_active, current_branch, head_ref


def test_branch_active_include_all_exclude_protected() -> None:
    inc, exc = ["*"], ["main", "release/*"]
    assert branch_active("feature/x", inc, exc) is True
    assert branch_active("fix/y", inc, exc) is True
    assert branch_active("main", inc, exc) is False
    assert branch_active("release/0.6.3", inc, exc) is False


def test_exclude_wins_over_include() -> None:
    assert branch_active("main", ["main"], ["main"]) is False


def test_include_narrowing() -> None:
    assert branch_active("feature/x", ["feature/*"], []) is True
    assert branch_active("hotfix/x", ["feature/*"], []) is False


def test_detached_head_is_active() -> None:
    # no branch name to gate on → the explicit `ckg watch` wins
    assert branch_active("", ["feature/*"], ["*"]) is True


def test_read_branch_from_head(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/feature/abc\n")
    assert current_branch(tmp_path) == "feature/abc"
    assert head_ref(tmp_path) == "ref: refs/heads/feature/abc"


def test_detached_head_reads_empty_branch(tmp_path: Path) -> None:
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("a1b2c3d4\n")
    assert current_branch(tmp_path) == ""
    assert head_ref(tmp_path) == "a1b2c3d4"


def test_no_git_dir() -> None:
    assert current_branch("/nonexistent/path/xyz") == ""
    assert head_ref("/nonexistent/path/xyz") == ""
