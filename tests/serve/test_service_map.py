"""ENH-020 C-full (increment 2): cross-service call graph — match a member's
outbound ServiceCall to a Route in another member."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.engine import _Engine
from agentforge_graph.serve.federation import FederatedEngine, _compile_route
from agentforge_graph.serve.server import federated_tools
from agentforge_graph.serve.tools import CkgServicesMap
from agentforge_graph.serve.workspace import WorkspaceConfig

ORDERS_APP = """\
from fastapi import FastAPI

app = FastAPI()


@app.get("/v1/orders")
def list_orders():
    return []


@app.get("/v1/orders/{oid}")
def get_order(oid):
    return {}
"""

GATEWAY = """\
import requests


def proxy():
    return requests.get("http://orders/v1/orders")


def one():
    return requests.get("http://orders/v1/orders/42")


def missing():
    return requests.get("http://orders/v1/nope")
"""


async def _two_service_workspace(tmp_path: Path) -> Path:
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "app.py").write_text(ORDERS_APP)
    cg = await CodeGraph.index(repo_path=tmp_path / "orders")
    await cg.close()
    (tmp_path / "gateway").mkdir()
    (tmp_path / "gateway" / "client.py").write_text(GATEWAY)
    cg = await CodeGraph.index(repo_path=tmp_path / "gateway")
    await cg.close()
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        "members:\n  - name: gateway\n    repo: gateway\n  - name: orders\n    repo: orders\n"
    )
    return ws


async def test_service_map_links_caller_to_route(tmp_path: Path) -> None:
    ws = await _two_service_workspace(tmp_path)
    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(ws))
    m = await fed.service_map()

    # two calls match routes (exact + path-param); the /v1/nope call does not
    assert m["edge_count"] == 2
    assert all(e["from_service"] == "gateway" and e["to_service"] == "orders" for e in m["edges"])
    assert {e["call_path"] for e in m["edges"]} == {"/v1/orders", "/v1/orders/42"}
    # the param route's handler is carried through
    param_edge = next(e for e in m["edges"] if e["call_path"] == "/v1/orders/42")
    assert param_edge["route_path"] == "/v1/orders/{oid}" and param_edge["handler"]
    # the unmatched call is reported, not dropped
    assert any(u["path"] == "/v1/nope" for u in m["unresolved"])


async def test_services_map_tool_over_workspace(tmp_path: Path) -> None:
    ws = await _two_service_workspace(tmp_path)
    tools = {t.name: t for t in federated_tools(ws)}
    assert "ckg_services_map" in tools  # federation-only tool present
    out = json.loads(await tools["ckg_services_map"].run())
    assert out["edge_count"] == 2 and set(out["services"]) == {"gateway", "orders"}


async def test_services_map_needs_a_workspace(tmp_path: Path) -> None:
    repo = tmp_path / "solo"
    repo.mkdir()
    (repo / "m.py").write_text("x = 1\n")
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()
    out = json.loads(await CkgServicesMap(_Engine(str(repo))).run())
    assert "error" in out  # single repo → needs --workspace


def test_compile_route_matches_path_params() -> None:
    assert _compile_route("/v1/orders").match("/v1/orders")
    assert _compile_route("/v1/orders/{id}").match("/v1/orders/42")
    assert _compile_route("/v1/orders/:id").match("/v1/orders/42")
    assert _compile_route("/u/<uid>/p").match("/u/7/p")
    assert not _compile_route("/v1/orders").match("/v1/orders/42")
    assert not _compile_route("/v1/orders/{id}").match("/v1/orders")
