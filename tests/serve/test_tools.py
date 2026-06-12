"""The six tools driven directly over a fixture index (FakeEmbedder via a
fake-driver ckg.yaml). Asserts result shapes, guardrail clamping, envelopes."""

from __future__ import annotations

import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.engine import _Engine
from agentforge_graph.serve.tools import (
    CkgImpact,
    CkgNeighbors,
    CkgRepoMap,
    CkgSearch,
    CkgStatus,
    CkgSymbol,
)

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
FAKE_YAML = "embed:\n  driver: fake\n  dim: 16\nserve:\n  max_depth: 2\n  max_k: 3\n"


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[_Engine]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    (repo / "ckg.yaml").write_text(FAKE_YAML)
    cfg = str(repo / "ckg.yaml")
    cg = await CodeGraph.index(repo_path=repo, config=cfg, embed=True)
    await cg.close()
    eng = _Engine(repo, cfg)
    try:
        yield eng
    finally:
        await eng.close()


async def _square_id(engine: _Engine) -> str:
    from agentforge_graph.core import GraphQuery, SymbolID

    cg = await engine.code_graph()
    nodes = (await cg.store.graph.query(GraphQuery(limit=10000))).nodes
    return next(n.id for n in nodes if SymbolID.parse(n.id).descriptor == "square().")


async def test_repo_map_tool(engine: _Engine) -> None:
    out = await CkgRepoMap(engine).run(budget_tokens=2000, focus=[])
    assert "mathutils.py:" in out
    assert "def square" in out


async def test_search_tool_returns_pack_json(engine: _Engine) -> None:
    out = await CkgSearch(engine).run(query="circle area", k=2, mode="context")
    data = json.loads(out)
    assert "items" in data
    assert data["tool_api_version"] == "1.0"
    assert "dirty" in data
    assert "truncated" in data


async def test_search_clamps_k(engine: _Engine) -> None:
    # k=99 but serve.max_k=3 -> at most 3 vector hits feed the pack
    out = await CkgSearch(engine).run(query="square", k=99, mode="similar")
    data = json.loads(out)
    chunk_items = [i for i in data["items"] if i["kind"] == "Chunk"]
    assert len(chunk_items) <= 3


async def test_impact_tool(engine: _Engine) -> None:
    out = await CkgImpact(engine).run(symbol_id=await _square_id(engine), depth=1)
    data = json.loads(out)
    names = {i["name"] for i in data["items"]}
    assert {"cube", "area"} & names  # callers of square


async def test_impact_clamps_depth(engine: _Engine) -> None:
    out = await CkgImpact(engine).run(symbol_id=await _square_id(engine), depth=99)
    assert json.loads(out)["tool_api_version"] == "1.0"  # ran without blowing up


async def test_neighbors_tool(engine: _Engine) -> None:
    out = await CkgNeighbors(engine).run(symbol_id=await _square_id(engine), edge_kinds=["CALLS"])
    data = json.loads(out)
    assert all(e["kind"] == "CALLS" for e in data["edges"])
    assert data["edges"]


async def test_symbol_tool_by_name(engine: _Engine) -> None:
    out = await CkgSymbol(engine).run(name="square", path="mathutils.py")
    data = json.loads(out)
    assert any(i["name"] == "square" for i in data.get("items", []))


async def test_symbol_tool_not_found(engine: _Engine) -> None:
    out = await CkgSymbol(engine).run(name="nope", path="nowhere.py")
    assert json.loads(out)["error"] == "symbol not found"


async def test_status_tool(engine: _Engine) -> None:
    data = json.loads(await CkgStatus(engine).run())
    assert data["nodes"] > 0
    assert data["by_kind"].get("Function") == 3
    assert data["dirty"] is False
