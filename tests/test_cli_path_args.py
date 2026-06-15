"""ENH-006: every ckg subcommand accepts the same repo-path argument.

A positional ``[path]`` defaulting to ``.`` on every subcommand, with
``--path`` / ``--repo`` accepted as back-compat aliases. Precedence:
positional > ``--path``/``--repo`` > ``.``. This test locks the convention so
it cannot drift again.
"""

from __future__ import annotations

import pytest

from agentforge_graph.cli import _resolve_repo_path, build_parser


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
def test_repo_path_forms(cmd: str, lead: list[str], positional: bool) -> None:
    # --path alias parses and resolves everywhere
    assert _path([cmd, *lead, "--path", "/tmp/x"]) == "/tmp/x"
    # --repo alias parses and resolves everywhere (back-compat for serve-mcp)
    assert _path([cmd, *lead, "--repo", "/tmp/x"]) == "/tmp/x"
    # default is the cwd
    assert _path([cmd, *lead]) == "."
    if positional:
        assert _path([cmd, *lead, "/tmp/x"]) == "/tmp/x"


def test_positional_beats_alias() -> None:
    # positional wins over --path / --repo when both are given
    assert _path(["index", "/pos", "--path", "/alias"]) == "/pos"
    assert _path(["index", "/pos", "--repo", "/alias"]) == "/pos"


def test_legacy_invocations_still_parse() -> None:
    # the historically-documented forms keep working
    assert _path(["map", "--path", "/tmp/x"]) == "/tmp/x"
    assert _path(["serve-mcp", "--repo", "/tmp/x"]) == "/tmp/x"
    assert _path(["status", "/tmp/x"]) == "/tmp/x"
