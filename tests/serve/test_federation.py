"""ENH-020 (C-lite): federated MCP over a workspace of members.

Survey tools (status/routes/search/decisions) fan across all members and tag
results by service; pinpoint tools (symbol/impact/…/repo_map) take a `service`
to pick one. A single repo is unchanged (no `services` envelope).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve import code_graph_tools
from agentforge_graph.serve.federation import (
    AmbiguousMember,
    FederatedEngine,
    MemberNotFound,
)
from agentforge_graph.serve.server import federated_tools
from agentforge_graph.serve.workspace import WorkspaceConfig


async def _make_repo(d: Path, name: str) -> None:
    d.mkdir(parents=True)
    (d / f"{name}.py").write_text("def f():\n    return 1\n")
    cg = await CodeGraph.index(repo_path=d)
    await cg.close()


def _write_workspace(path: Path, members: list[tuple[str, str]]) -> None:
    lines = ["members:"]
    for name, repo in members:
        lines += [f"  - name: {name}", f"    repo: {repo}"]
    path.write_text("\n".join(lines) + "\n")


# --- workspace manifest ----------------------------------------------------


def test_workspace_load_resolves_members(tmp_path: Path) -> None:
    ws_path = tmp_path / "workspace.yaml"
    _write_workspace(ws_path, [("gateway", "a"), ("orders", "services/b")])
    ws = WorkspaceConfig.load(ws_path)
    assert [m.name for m in ws.members] == ["gateway", "orders"]
    # repo paths resolve relative to the manifest's directory
    assert ws.member_repo(ws.members[1]) == tmp_path / "services" / "b"


def test_workspace_load_rejects_empty_and_dupes(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("workspace: x\n")
    with pytest.raises(ValueError):
        WorkspaceConfig.load(empty)
    dupe = tmp_path / "dupe.yaml"
    _write_workspace(dupe, [("a", "x"), ("a", "y")])
    with pytest.raises(ValueError):
        WorkspaceConfig.load(dupe)


# --- FederatedEngine selectors ---------------------------------------------


def test_targets_and_one(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    ws_path = tmp_path / "workspace.yaml"
    _write_workspace(ws_path, [("a", "a"), ("b", "b")])
    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(ws_path))

    assert {n for n, _ in fed.targets()} == {"a", "b"}  # fan all
    assert {n for n, _ in fed.targets("a")} == {"a"}  # one named
    with pytest.raises(MemberNotFound):
        fed.targets("nope")

    assert fed.one("a") is fed.members["a"]
    with pytest.raises(AmbiguousMember):  # pinpoint with >1 member needs a service
        fed.one()
    with pytest.raises(MemberNotFound):
        fed.one("nope")


# --- federated tools --------------------------------------------------------


async def test_status_fans_across_members(tmp_path: Path) -> None:
    await _make_repo(tmp_path / "a", "a")
    await _make_repo(tmp_path / "b", "b")
    ws_path = tmp_path / "workspace.yaml"
    _write_workspace(ws_path, [("a", "a"), ("b", "b")])
    tools = {t.name: t for t in federated_tools(ws_path)}

    result = json.loads(await tools["ckg_status"].run())
    assert set(result["services"]) == {"a", "b"}  # both services reported


async def test_routes_merge_carries_service_envelope(tmp_path: Path) -> None:
    await _make_repo(tmp_path / "a", "a")
    await _make_repo(tmp_path / "b", "b")
    ws_path = tmp_path / "workspace.yaml"
    _write_workspace(ws_path, [("a", "a"), ("b", "b")])
    tools = {t.name: t for t in federated_tools(ws_path)}

    result = json.loads(await tools["ckg_routes"].run())
    assert "services" in result and set(result["services"]) == {"a", "b"}
    assert result["count"] == 0  # the tiny repos have no routes


async def test_pinpoint_tool_requires_service_when_ambiguous(tmp_path: Path) -> None:
    await _make_repo(tmp_path / "a", "a")
    await _make_repo(tmp_path / "b", "b")
    ws_path = tmp_path / "workspace.yaml"
    _write_workspace(ws_path, [("a", "a"), ("b", "b")])
    tools = {t.name: t for t in federated_tools(ws_path)}

    out = json.loads(await tools["ckg_explain"].run(symbol_id="whatever"))
    assert "error" in out and "service" in out["error"]


async def test_unknown_service_is_a_clean_error(tmp_path: Path) -> None:
    await _make_repo(tmp_path / "a", "a")
    ws_path = tmp_path / "workspace.yaml"
    _write_workspace(ws_path, [("a", "a")])
    tools = {t.name: t for t in federated_tools(ws_path)}

    out = json.loads(await tools["ckg_status"].run(service="nope"))
    assert "error" in out


async def test_single_repo_has_no_services_envelope(tmp_path: Path) -> None:
    await _make_repo(tmp_path / "solo", "solo")
    tools = {t.name: t for t in code_graph_tools(str(tmp_path / "solo"))}

    result = json.loads(await tools["ckg_status"].run())
    assert "services" not in result  # legacy single-repo shape preserved
    assert "indexed_commit" in result
