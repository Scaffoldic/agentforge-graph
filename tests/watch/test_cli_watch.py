"""feat-014: CLI wiring for `ckg watch` and `ckg ci init` (sync — main() owns the
event loop)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentforge_graph.ci import MARKER, WORKFLOW_REL_PATH
from agentforge_graph.cli import main


@pytest.fixture(autouse=True)
def _clean_env():  # type: ignore[no-untyped-def]
    # main() bridges --read-only to the process env; keep tests isolated so a
    # --read-only case never leaks CKG_READ_ONLY into the next test's store.
    os.environ.pop("CKG_READ_ONLY", None)
    yield
    os.environ.pop("CKG_READ_ONLY", None)


def _tiny_repo(root: Path) -> Path:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text("def a():\n    return 1\n")
    return root


def test_ci_init_print_writes_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["ci", "init", "--print", "--path", str(tmp_path)])
    assert rc == 0
    assert MARKER in capsys.readouterr().out
    assert not (tmp_path / WORKFLOW_REL_PATH).exists()


def test_ci_init_creates_file(tmp_path: Path) -> None:
    rc = main(["ci", "init", "--path", str(tmp_path)])
    assert rc == 0
    assert (tmp_path / WORKFLOW_REL_PATH).read_text().startswith(MARKER)


def test_watch_status(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _tiny_repo(tmp_path)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()  # drop index output
    rc = main(["watch", "--status", "--path", str(repo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "trigger:" in out
    assert "on-commit" in out  # the default


def test_watch_once_refreshes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _tiny_repo(tmp_path)
    assert main(["index", str(repo)]) == 0
    (repo / "pkg" / "extra.py").write_text("def b():\n    return 2\n")
    capsys.readouterr()
    rc = main(["watch", "--once", "--path", str(repo)])
    assert rc == 0


def test_watch_refuses_central_store(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _tiny_repo(tmp_path)
    cfg = tmp_path / "agentforge.yaml"
    cfg.write_text(f"app:\n  store:\n    central_root: {tmp_path / 'central'}\n")
    rc = main(["watch", "--path", str(repo), "--config", str(cfg)])
    assert rc == 2
    assert "central" in capsys.readouterr().err


def test_watch_refuses_read_only(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _tiny_repo(tmp_path)
    assert main(["index", str(repo)]) == 0
    capsys.readouterr()
    rc = main(["watch", "--read-only", "--path", str(repo)])
    assert rc == 2
    assert "read-only" in capsys.readouterr().err
