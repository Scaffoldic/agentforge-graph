"""feat-015 chunk 7: the query: config block and its wiring.

Covers QueryConfig parsing/defaults/to_settings and that disabling the surface
(query.enabled / query.allow_in_mcp) is honoured at the CLI, the engine, and the
MCP tool-registration gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.config import QueryConfig
from agentforge_graph.ingest import CodeGraph

_SRC = "class Repo:\n    def save(self): ...\n"


def test_defaults() -> None:
    q = QueryConfig.load(None)
    assert q.enabled is True and q.allow_in_mcp is True
    assert (q.max_rows, q.timeout_ms, q.max_expansions) == (1000, 5000, 50_000)


def test_parses_block(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text("query:\n  enabled: false\n  max_rows: 25\n  allow_in_mcp: false\n")
    q = QueryConfig.load(y)
    assert q.enabled is False and q.allow_in_mcp is False and q.max_rows == 25


def test_to_settings_applies_limit() -> None:
    q = QueryConfig.load(None)
    assert q.to_settings().max_rows == 1000
    assert q.to_settings(10).max_rows == 10  # caller limit lowers the cap
    assert q.to_settings(9999).max_rows == 1000  # but never raises it


def test_block_key_is_discovered() -> None:
    from agentforge_graph.config import block_keys

    assert "query" in block_keys()


@pytest.fixture
async def indexed(tmp_path: Path) -> Path:
    (tmp_path / "app.py").write_text(_SRC)
    cg = await CodeGraph.index(repo_path=tmp_path)
    await cg.close()
    return tmp_path


def test_cli_refuses_when_disabled(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    cfg = indexed / "ckg.yaml"
    cfg.write_text("query:\n  enabled: false\n")
    rc = main(
        [
            "query",
            "--path",
            str(indexed),
            "--config",
            str(cfg),
            "--graph",
            "MATCH (c:Class) RETURN c.name",
        ]
    )
    assert rc == 2
    assert "disabled" in capsys.readouterr().err


async def test_engine_reports_disabled(indexed: Path) -> None:
    from agentforge_graph.config import resolve_config
    from agentforge_graph.serve.engine import _Engine

    cfg = indexed / "ckg.yaml"
    cfg.write_text("query:\n  enabled: false\n")
    eng = _Engine(indexed, resolve_config(str(cfg), str(indexed)))
    out = await eng.query_graph("MATCH (c:Class) RETURN c.name")
    assert "disabled" in out["error"]


def test_tool_gated_out_when_allow_in_mcp_false(tmp_path: Path) -> None:
    from agentforge_graph.serve import code_graph_tools

    (tmp_path / "app.py").write_text(_SRC)
    (tmp_path / "ckg.yaml").write_text("query:\n  allow_in_mcp: false\n")
    tools = {t.name for t in code_graph_tools(str(tmp_path), str(tmp_path / "ckg.yaml"))}
    assert "ckg_query" not in tools  # capable backend, but MCP exposure is off
    assert "ckg_search" in tools  # other tools unaffected
