"""CLI: `ckg embed` and `ckg index --embed` with a fake-driver ckg.yaml
(no AWS needed)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentforge_graph.cli import main

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
FAKE_YAML = "embed:\n  driver: fake\n  dim: 16\n"


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    (repo / "ckg.yaml").write_text(FAKE_YAML)
    return repo


def test_embed_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    cfg = str(repo / "ckg.yaml")
    assert main(["index", str(repo), "--config", cfg]) == 0
    capsys.readouterr()
    rc = main(["embed", str(repo), "--config", cfg])
    assert rc == 0
    out = capsys.readouterr().out
    assert "embedded" in out
    assert "model fake" in out


def test_index_embed_flag(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path)
    rc = main(["index", str(repo), "--embed", "--config", str(repo / "ckg.yaml")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "indexed 2 files" in out
    assert "embedded" in out
