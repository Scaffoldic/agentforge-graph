"""ckg CLI smoke tests: `ckg index` over the fixture repo, arg parsing."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentforge_graph.cli import build_parser, main
from agentforge_graph.main import main as console_main


def test_index_smoke(tmp_path: Path, python_repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    rc = main(["index", str(repo)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "indexed 2 files" in out
    assert "Class=1" in out
    assert "CALLS=2" in out
    assert (repo / ".ckg" / "graph.kuzu").exists()


def test_index_language_filter(
    tmp_path: Path, python_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    rc = main(["index", str(repo), "--lang", "rust"])
    assert rc == 0
    assert "indexed 0 files" in capsys.readouterr().out


def test_parser_requires_subcommand() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_console_main_dispatches(
    tmp_path: Path, python_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(python_repo, repo)
    monkeypatch.setattr("sys.argv", ["ckg", "index", str(repo)])
    with pytest.raises(SystemExit) as exc:
        console_main()
    assert exc.value.code == 0
