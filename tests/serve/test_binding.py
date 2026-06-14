"""Dual binding: code_graph_tools (Agent) + build_mcp_server (MCP stdio/http)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from agentforge_core.contracts.tool import Tool

from agentforge_graph.serve import build_mcp_server, code_graph_tools

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"

_EXPECTED = {
    "ckg_repo_map",
    "ckg_search",
    "ckg_symbol",
    "ckg_impact",
    "ckg_neighbors",
    "ckg_status",
    "ckg_routes",
    "ckg_decisions",
    "ckg_explain",
}


def test_code_graph_tools_are_tool_instances() -> None:
    tools = code_graph_tools(".")
    assert {t.name for t in tools} == _EXPECTED
    assert all(isinstance(t, Tool) for t in tools)
    # one shared engine across the toolset
    assert len({id(t._engine) for t in tools}) == 1  # type: ignore[attr-defined]


def test_tools_have_schemas_and_descriptions() -> None:
    for t in code_graph_tools("."):
        assert t.description.strip()
        schema = type(t).input_schema.model_json_schema()
        assert schema["type"] == "object"


def test_build_mcp_server_registers_tools(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    server = build_mcp_server(repo)  # stdio default; constructs without serving
    assert server is not None


def test_build_mcp_server_http_transport(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    # http builds the streamable-HTTP server (mounted at /mcp) without serving
    server = build_mcp_server(repo, transport="http", host="0.0.0.0", port=9001)
    assert server is not None


def test_build_mcp_server_rejects_unknown_transport(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    with pytest.raises(ValueError, match="unknown MCP transport"):
        build_mcp_server(repo, transport="grpc")  # type: ignore[arg-type]
