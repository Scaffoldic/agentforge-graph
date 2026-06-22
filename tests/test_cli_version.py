"""`ckg --version` / `-V` — prints the package version and exits 0, even though a
subcommand is otherwise required (the version action short-circuits parsing)."""

from __future__ import annotations

import pytest

from agentforge_graph import __version__
from agentforge_graph.cli import main


def test_version_flag_prints_and_exits_zero(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert out.strip() == f"ckg {__version__}"


def test_short_version_flag(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc:
        main(["-V"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.startswith("ckg ")


def test_version_is_resolvable() -> None:
    # the installed package exposes a real version (not the source-checkout fallback)
    assert __version__ and __version__ != "0.0.0+unknown"
