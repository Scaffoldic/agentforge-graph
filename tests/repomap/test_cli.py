"""ckg map CLI."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentforge_graph.cli import main

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    assert main(["index", str(repo)]) == 0
    return repo


def test_map_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    capsys.readouterr()
    rc = main(["map", "--path", str(repo), "--budget", "2000"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "mathutils.py:" in out
    assert "def square" in out


def test_map_cli_scope(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    capsys.readouterr()
    rc = main(["map", "--path", str(repo), "--scope", "mathutils.py"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "mathutils.py:" in out
    assert "shapes.py:" not in out
