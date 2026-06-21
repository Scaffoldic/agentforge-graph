"""ENH-020 C-full: JS/TS outbound HTTP calls (fetch / axios) → ServiceCall nodes."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.ingest import CodeGraph

SRC = """\
const axios = require("axios");

async function getOrders() {
  return fetch("http://orders/v1/orders");
}

async function charge() {
  return fetch("http://payments/v1/charge", { method: "POST" });
}

async function getUser() {
  return axios.get("http://users/v1/me");
}

function dynamic(u) {
  return fetch(u);  // computed URL — not captured
}
"""


async def test_captures_fetch_and_axios(tmp_path: Path) -> None:
    repo = tmp_path / "web"
    repo.mkdir()
    (repo / "client.js").write_text(SRC)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        calls = await cg.service_calls()
    finally:
        await cg.close()
    by_path = {c.path: c for c in calls}
    assert set(by_path) == {"/v1/orders", "/v1/charge", "/v1/me"}
    # fetch defaults to GET; the { method: "POST" } option is honored
    assert by_path["/v1/orders"].method == "GET" and by_path["/v1/orders"].framework == "fetch"
    assert by_path["/v1/charge"].method == "POST"
    assert by_path["/v1/me"].method == "GET" and by_path["/v1/me"].framework == "axios"


def test_fetch_method_reads_options() -> None:
    from tree_sitter import Parser

    from agentforge_graph.frameworks.packs._js_ast import js_language
    from agentforge_graph.frameworks.packs.jshttpclient import _fetch_method

    src = b'fetch("/x", { method: "delete" });'
    root = Parser(js_language("js")).parse(src).root_node
    # locate the arguments node of the call
    call = root.named_children[0].named_children[0]
    args = call.child_by_field_name("arguments")
    assert _fetch_method(args, src) == "DELETE"
