"""ENH-006 + ENH-019: the repo-path argument across ckg subcommands.

ENH-006: a positional ``[path]`` on every subcommand, with ``--path`` /
``--repo`` accepted as back-compat aliases; precedence positional > alias.

ENH-019: when no path is given, the default is the repo root **discovered
upward from the cwd** (like ``git``), falling back to ``.`` when no repo marker
is found. The precedence tests below neutralise discovery so they assert the
explicit-argument rules in isolation; the discovery behaviour has its own tests.
"""

from __future__ import annotations

import pytest

from agentforge_graph import cli
from agentforge_graph.cli import _resolve_repo_path, build_parser, discover_repo_root


def _path(argv: list[str]) -> str:
    args = build_parser().parse_args(argv)
    _resolve_repo_path(args)
    return str(args.path)


# (command, leading positionals before path, supports a positional path slot)
CASES = [
    ("index", [], True),
    ("status", [], True),
    ("embed", [], True),
    ("query", ["q"], False),  # leading positional is the NL query
    ("map", [], True),
    ("routes", [], True),
    ("decisions", [], True),
    ("enrich", [], True),
    ("summaries", [], True),
    ("tagged", ["Repository"], True),  # leading positional is the pattern name
    ("serve-mcp", [], True),
]


@pytest.mark.parametrize("cmd,lead,positional", CASES, ids=[c[0] for c in CASES])
def test_repo_path_forms(
    cmd: str, lead: list[str], positional: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    # neutralise ENH-019 discovery so these assert the explicit-precedence rules
    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: None)
    # --path alias parses and resolves everywhere
    assert _path([cmd, *lead, "--path", "/tmp/x"]) == "/tmp/x"
    # --repo alias parses and resolves everywhere (back-compat for serve-mcp)
    assert _path([cmd, *lead, "--repo", "/tmp/x"]) == "/tmp/x"
    # default with no marker discovered → the cwd
    assert _path([cmd, *lead]) == "."
    if positional:
        assert _path([cmd, *lead, "/tmp/x"]) == "/tmp/x"


def test_positional_beats_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: None)
    # positional wins over --path / --repo when both are given
    assert _path(["index", "/pos", "--path", "/alias"]) == "/pos"
    assert _path(["index", "/pos", "--repo", "/alias"]) == "/pos"


def test_legacy_invocations_still_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "discover_repo_root", lambda _start: None)
    # the historically-documented forms keep working
    assert _path(["map", "--path", "/tmp/x"]) == "/tmp/x"
    assert _path(["serve-mcp", "--repo", "/tmp/x"]) == "/tmp/x"
    assert _path(["status", "/tmp/x"]) == "/tmp/x"


# --- ENH-019: working-directory auto-discovery -----------------------------


def _mk_marker(root, marker: str) -> None:
    if marker in (".ckg", ".git"):
        (root / marker).mkdir()
    else:
        (root / marker).write_text("")


@pytest.mark.parametrize("marker", [".ckg", "agentforge.yaml", "ckg.yaml", ".git"])
def test_discover_finds_each_marker(tmp_path, marker: str) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _mk_marker(root, marker)
    sub = root / "src" / "pkg"
    sub.mkdir(parents=True)
    assert discover_repo_root(sub) == root.resolve()


def test_discover_returns_root_itself(tmp_path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _mk_marker(root, ".ckg")
    assert discover_repo_root(root) == root.resolve()


def test_discover_returns_none_without_markers(tmp_path) -> None:
    sub = tmp_path / "a" / "b"
    sub.mkdir(parents=True)
    assert discover_repo_root(sub) is None


def test_discover_nearest_wins(tmp_path) -> None:
    outer = tmp_path / "outer"
    (outer / ".git").mkdir(parents=True)
    inner = outer / "services" / "inner"
    (inner / ".ckg").mkdir(parents=True)
    deep = inner / "src"
    deep.mkdir()
    # the nearest marked dir wins — inner (.ckg), not the outer git root
    assert discover_repo_root(deep) == inner.resolve()


def test_default_uses_discovery_from_subdir(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _mk_marker(root, ".ckg")
    sub = root / "src"
    sub.mkdir()
    monkeypatch.chdir(sub)
    args = build_parser().parse_args(["status"])
    _resolve_repo_path(args)
    assert args.path == str(root.resolve())


def test_explicit_path_skips_discovery(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    _mk_marker(root, ".ckg")
    sub = root / "src"
    sub.mkdir()
    monkeypatch.chdir(sub)
    # an explicit path always wins, discovery never runs
    assert _path(["status", "/explicit"]) == "/explicit"
