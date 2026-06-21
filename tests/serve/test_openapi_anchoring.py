"""ENH-020 C-full: OpenAPI anchoring — match calls against a service's declared
contract, including contract-first services with no detected framework, and dedupe
a framework route against its spec twin."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.federation import (
    FederatedEngine,
    _normalize_template,
    _openapi_routes,
)
from agentforge_graph.serve.workspace import WorkspaceConfig

BILLING_SPEC = """\
openapi: 3.0.0
info: { title: billing, version: "1" }
paths:
  /v1/invoices:
    post:
      operationId: createInvoice
  /v1/invoices/{id}:
    get:
      operationId: getInvoice
"""

GATEWAY = """\
import requests


def create():
    return requests.post("http://billing/v1/invoices")


def fetch():
    return requests.get("http://billing/v1/invoices/42")
"""

# a service with BOTH a framework route and an OpenAPI entry for the same path
ORDERS_APP = """\
from fastapi import FastAPI

app = FastAPI()


@app.get("/v1/orders")
def list_orders():
    return []
"""
ORDERS_SPEC = """\
openapi: 3.0.0
info: { title: orders, version: "1" }
paths:
  /v1/orders:
    get:
      operationId: listOrders
"""


async def _index(repo: Path) -> None:
    cg = await CodeGraph.index(repo_path=repo)
    await cg.close()


async def test_contract_first_service_is_matched_via_openapi(tmp_path: Path) -> None:
    (tmp_path / "billing").mkdir()
    (tmp_path / "billing" / "openapi.yaml").write_text(BILLING_SPEC)  # no framework code
    await _index(tmp_path / "billing")
    (tmp_path / "gateway").mkdir()
    (tmp_path / "gateway" / "client.py").write_text(GATEWAY)
    await _index(tmp_path / "gateway")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        "members:\n  - name: gateway\n    repo: gateway\n  - name: billing\n    repo: billing\n"
    )

    m = await FederatedEngine.from_workspace(WorkspaceConfig.load(ws)).service_map()
    assert m["edge_count"] == 2
    assert all(e["to_service"] == "billing" and e["via"] == "openapi" for e in m["edges"])
    # the operationId is carried as the handler
    assert {e["handler"] for e in m["edges"]} == {"createInvoice", "getInvoice"}


async def test_framework_and_spec_twin_does_not_create_ambiguity(tmp_path: Path) -> None:
    (tmp_path / "orders").mkdir()
    (tmp_path / "orders" / "app.py").write_text(ORDERS_APP)
    (tmp_path / "orders" / "openapi.yaml").write_text(ORDERS_SPEC)  # twin of the route
    await _index(tmp_path / "orders")
    (tmp_path / "gateway").mkdir()
    (tmp_path / "gateway" / "client.py").write_text(
        'import requests\n\n\ndef p():\n    return requests.get("http://orders/v1/orders")\n'
    )
    await _index(tmp_path / "gateway")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        "members:\n  - name: gateway\n    repo: gateway\n  - name: orders\n    repo: orders\n"
    )

    m = await FederatedEngine.from_workspace(WorkspaceConfig.load(ws)).service_map()
    # exactly one edge — the spec twin is deduped, framework route wins (has handler)
    assert m["edge_count"] == 1
    assert m["edges"][0]["via"] == "framework" and not m["unresolved"]


def test_openapi_routes_parsing(tmp_path: Path) -> None:
    (tmp_path / "openapi.yaml").write_text(BILLING_SPEC)
    got = {(m, p, op) for (m, p, op) in _openapi_routes(tmp_path)}
    assert got == {
        ("POST", "/v1/invoices", "createInvoice"),
        ("GET", "/v1/invoices/{id}", "getInvoice"),
    }
    assert _openapi_routes(tmp_path / "missing") == []  # no spec → empty


def test_normalize_template_is_param_agnostic() -> None:
    assert _normalize_template("/v1/orders/{oid}") == _normalize_template("/v1/orders/{id}")
    assert _normalize_template("/v1/orders/:id") == "/v1/orders/{}"
    assert _normalize_template("/v1/orders") != _normalize_template("/v1/orders/{id}")
