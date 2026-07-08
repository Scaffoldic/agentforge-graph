"""feat-015 chunk 6: the ckg_query MCP tool + engine.query_graph.

Functional over a real indexed repo (embedded Kuzu). Asserts the staleness +
query-language envelope, structured errors (never raised into the tool layer),
and that ckg_status reports the query surface.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.engine import _Engine
from agentforge_graph.serve.tools import CkgQuery, CkgStatus

_SRC = """\
class Repo:
    def save(self): ...

class Cache:
    def get(self): ...
"""


@pytest.fixture
async def repo(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(_SRC)
    cg = await CodeGraph.index(repo_path=tmp_path)
    await cg.close()
    return tmp_path


def _engine(repo: Path) -> _Engine:
    return _Engine(repo)


async def test_query_tool_returns_rows_with_envelope(repo: Path) -> None:
    tool = CkgQuery(_engine(repo))
    out = json.loads(await tool.run(query="MATCH (c:Class) RETURN c.name"))
    assert set(out["columns"]) == {"c.name"}
    assert {r[0] for r in out["rows"]} == {"Repo", "Cache"}
    assert out["truncated"] is False
    # envelope: staleness + tool/query-language version
    assert "indexed_commit" in out and "dirty" in out
    assert out["tool_api_version"] == "1.0"
    assert out["query_lang_version"] == "1.0"


async def test_query_tool_limit(repo: Path) -> None:
    tool = CkgQuery(_engine(repo))
    out = json.loads(await tool.run(query="MATCH (c:Class) RETURN c.name", limit=1))
    assert len(out["rows"]) == 1
    assert out["truncated"] is True and out["stopped_reason"] == "row_cap"


async def test_query_tool_error_is_structured_not_raised(repo: Path) -> None:
    tool = CkgQuery(_engine(repo))
    out = json.loads(await tool.run(query="MATCH (c:Bogus) RETURN c.name"))
    assert "error" in out and "Bogus" in out["error"]
    assert out["tool_api_version"] == "1.0"  # envelope still attached


async def test_status_reports_query_surface(repo: Path) -> None:
    out = json.loads(await CkgStatus(_engine(repo)).run())
    assert out["query"]["enabled"] is True
    assert out["query"]["lang_version"] == "1.0"
    assert "core" in out["query"]["capabilities"]
