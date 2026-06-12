"""ckg query CLI (fake-driver ckg.yaml, no AWS)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agentforge_graph.cli import main

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
FAKE_YAML = "embed:\n  driver: fake\n  dim: 16\n"


def _indexed_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    (repo / "ckg.yaml").write_text(FAKE_YAML)
    cfg = str(repo / "ckg.yaml")
    assert main(["index", str(repo), "--embed", "--config", cfg]) == 0
    return repo, cfg


def test_query_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, cfg = _indexed_repo(tmp_path)
    capsys.readouterr()
    rc = main(["query", "circle area radius", "--path", str(repo), "--config", cfg])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()  # rendered something


def test_query_cli_impact_by_symbol(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo, cfg = _indexed_repo(tmp_path)
    capsys.readouterr()
    rc = main(
        [
            "query",
            "--symbol",
            "ckg py proj mathutils.py square().",
            "--mode",
            "impact",
            "--path",
            str(repo),
            "--config",
            cfg,
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    # cube and area both call square -> appear as reverse-deps
    assert "cube" in out or "area" in out
