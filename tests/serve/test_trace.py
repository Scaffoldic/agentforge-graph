"""ENH-020 C-full: ckg_trace — walk the cross-service call graph from a service,
downstream (data flow) or upstream (blast radius)."""

from __future__ import annotations

import json
from pathlib import Path

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.federation import FederatedEngine
from agentforge_graph.serve.server import federated_tools
from agentforge_graph.serve.workspace import WorkspaceConfig

PAYMENTS = """\
from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/charge")
def charge():
    return {}
"""

ORDERS = """\
from fastapi import FastAPI
import requests

app = FastAPI()


@app.get("/v1/orders")
def list_orders():
    return requests.post("http://payments/v1/charge")
"""

GATEWAY = """\
import requests


def proxy():
    return requests.get("http://orders/v1/orders")
"""


async def _chain_workspace(tmp_path: Path) -> Path:
    for name, src, fname in [
        ("payments", PAYMENTS, "app.py"),
        ("orders", ORDERS, "app.py"),
        ("gateway", GATEWAY, "client.py"),
    ]:
        (tmp_path / name).mkdir()
        (tmp_path / name / fname).write_text(src)
        cg = await CodeGraph.index(repo_path=tmp_path / name)
        await cg.close()
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        "members:\n"
        "  - name: gateway\n    repo: gateway\n"
        "  - name: orders\n    repo: orders\n"
        "  - name: payments\n    repo: payments\n"
    )
    return ws


async def test_trace_downstream_follows_the_chain(tmp_path: Path) -> None:
    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(await _chain_workspace(tmp_path)))
    t = await fed.trace("gateway", direction="downstream")
    # gateway → orders → payments
    assert t["reached"] == ["orders", "payments"]
    assert {(h["from_service"], h["to_service"]) for h in t["hops"]} == {
        ("gateway", "orders"),
        ("orders", "payments"),
    }


async def test_trace_upstream_is_blast_radius(tmp_path: Path) -> None:
    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(await _chain_workspace(tmp_path)))
    t = await fed.trace("payments", direction="upstream")
    # who reaches payments? orders directly, gateway transitively
    assert t["reached"] == ["gateway", "orders"]


async def test_trace_tool_and_errors(tmp_path: Path) -> None:
    tools = {t.name: t for t in federated_tools(await _chain_workspace(tmp_path))}
    assert "ckg_trace" in tools
    out = json.loads(await tools["ckg_trace"].run(service="gateway"))
    assert out["start"] == "gateway" and out["reached"] == ["orders", "payments"]
    # unknown service / bad direction → clean error, not a crash
    assert "error" in json.loads(await tools["ckg_trace"].run(service="nope"))
    assert "error" in json.loads(await tools["ckg_trace"].run(service="gateway", direction="x"))
