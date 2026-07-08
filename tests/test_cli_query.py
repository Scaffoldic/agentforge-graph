"""feat-015 chunk 5: the `ckg query --graph / --schema / --format` CLI.

End-to-end over a real indexed repo (embedded Kuzu), plus the reusable
cli_format helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.cli_format import render_json, render_table
from agentforge_graph.ingest import CodeGraph

_SRC = """\
class Repo:
    def save(self): ...

class Cache:
    def get(self): ...

def helper():
    return Repo()
"""


@pytest.fixture
async def indexed(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(_SRC)
    cg = await CodeGraph.index(repo_path=tmp_path)
    await cg.close()
    return tmp_path


# --- cli_format units -------------------------------------------------------


def test_render_table_aligns_and_headers() -> None:
    out = render_table(("name", "kind"), [("Repo", "Class"), ("helper", "Function")])
    lines = out.splitlines()
    assert lines[0].startswith("name")
    assert set(lines[1]) <= {"-", " "}
    assert "Repo" in out and "helper" in out


def test_render_table_empty_shows_header_and_no_rows() -> None:
    out = render_table(("name",), [])
    assert "name" in out and "(no rows)" in out


def test_render_json_shape() -> None:
    out = render_json(("name",), [("Repo",)], truncated=True, stopped_reason="row_cap")
    data = json.loads(out)
    assert data == {
        "columns": ["name"],
        "rows": [["Repo"]],
        "truncated": True,
        "stopped_reason": "row_cap",
    }


# --- CLI end-to-end ---------------------------------------------------------


def test_graph_query_table(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["query", "--path", str(indexed), "--graph", "MATCH (c:Class) RETURN c.name"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Repo" in out and "Cache" in out and "c.name" in out


def test_graph_query_json(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "query",
            "--path",
            str(indexed),
            "--graph",
            "MATCH (m:Method) RETURN m.name",
            "--format",
            "json",
        ]
    )
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["columns"] == ["m.name"]
    assert {r[0] for r in data["rows"]} == {"save", "get"}
    assert data["truncated"] is False


def test_schema_command(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["query", "--path", str(indexed), "--schema"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "query language v1.0" in out
    assert "Class" in out and "CALLS" in out
    assert "sym_path" not in out  # curated logical names, not physical columns
    assert "path" in out


def test_schema_json(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["query", "--path", str(indexed), "--schema", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert data["query_lang_version"] == "1.0"
    assert "Class" in data["node_kinds"]


def test_bad_query_exits_2(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["query", "--path", str(indexed), "--graph", "MATCH (c:Bogus) RETURN c.name"])
    assert rc == 2
    assert "query error" in capsys.readouterr().err


def test_limit_caps_rows(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(
        [
            "query",
            "--path",
            str(indexed),
            "--graph",
            "MATCH (n:Method) RETURN n.name",
            "--limit",
            "1",
        ]
    )
    err = capsys.readouterr().err
    assert rc == 0
    assert "truncated" in err  # 2 methods, capped to 1


def test_limit_without_graph_errors(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["query", "--path", str(indexed), "--limit", "5"])
    assert rc == 2
    assert "--limit only applies to --graph" in capsys.readouterr().err
