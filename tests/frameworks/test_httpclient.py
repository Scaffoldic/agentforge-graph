"""ENH-020 C-full (increment 1): outbound HTTP client calls become ServiceCall
nodes — the caller side of a cross-service edge."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.frameworks.packs.httpclient import _url_path
from agentforge_graph.ingest import CodeGraph

SRC = """\
import requests
import httpx


def fetch_orders():
    return requests.get("http://orders-svc/v1/orders")


def make_payment(amount):
    return httpx.post("https://payments/v1/charge?amount=1", json={"amount": amount})


def dynamic(url):
    return requests.get(url)  # non-literal URL — not captured


def not_a_call(session):
    return session.get("/local")  # client-instance call — not captured (conservative)
"""


async def _calls(tmp_path: Path) -> list:
    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "client.py").write_text(SRC)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        return await cg.service_calls()
    finally:
        await cg.close()


async def test_captures_requests_and_httpx_calls(tmp_path: Path) -> None:
    calls = await _calls(tmp_path)
    by_path = {c.path: c for c in calls}
    # both module-qualified literal calls captured; dynamic + instance calls are not
    assert set(by_path) == {"/v1/orders", "/v1/charge"}

    orders = by_path["/v1/orders"]
    assert (orders.method, orders.framework) == ("GET", "requests")
    assert orders.url == "http://orders-svc/v1/orders"

    charge = by_path["/v1/charge"]
    assert (charge.method, charge.framework) == ("POST", "httpx")
    assert charge.path == "/v1/charge"  # query string stripped


def test_service_calls_cli(tmp_path: Path, capsys) -> None:
    from agentforge_graph.cli import main

    repo = tmp_path / "svc"
    repo.mkdir()
    (repo / "client.py").write_text(SRC)
    assert main(["index", str(repo)]) == 0
    assert main(["service-calls", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "/v1/orders" in out and "/v1/charge" in out


def test_url_path_normalization() -> None:
    assert _url_path("http://orders/v1/orders") == "/v1/orders"
    assert _url_path("https://h:8080/a/b?x=1#f") == "/a/b"
    assert _url_path("/already/a/path") == "/already/a/path"
    assert _url_path("http://host-only") == "/"
    assert _url_path("v1/no-leading-slash") == "/v1/no-leading-slash"
