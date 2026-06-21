"""End-to-end: the 0.5 org-central-knowledge features over the bundled
microservices demo — ENH-018 (central hosting + read-only), ENH-019 (cwd
discovery) and ENH-020 (federation + cross-service tracing) in one flow.

Uses ``examples/microservices`` as the fixture so the demo and the test can't
drift. web → gateway → orders → payments (payments is contract-first OpenAPI).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from agentforge_graph.cli import discover_repo_root, main
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.federation import FederatedEngine
from agentforge_graph.serve.server import federated_tools
from agentforge_graph.serve.workspace import WorkspaceConfig
from agentforge_graph.store import repo_key

_EXAMPLES = Path(__file__).resolve().parents[2] / "examples" / "microservices"
_SERVICES = ("web", "gateway", "orders", "payments")


@pytest.fixture(autouse=True)
def _clean_read_only_env() -> None:
    # main(--read-only) bridges to the process env; keep tests isolated
    os.environ.pop("CKG_READ_ONLY", None)
    yield
    os.environ.pop("CKG_READ_ONLY", None)


def _stage(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the demo into tmp, point every service at a central store."""
    ws = tmp_path / "acme"
    shutil.copytree(_EXAMPLES, ws)
    central = tmp_path / "central"
    for s in _SERVICES:
        (ws / s / "ckg.yaml").write_text(f"store:\n  central_root: {central}\n")
    return ws, central


async def _stage_and_index(tmp_path: Path) -> tuple[Path, Path]:
    ws, central = _stage(tmp_path)
    for s in _SERVICES:
        cg = await CodeGraph.index(repo_path=ws / s)  # discovers ckg.yaml → central
        await cg.close()
    return ws, central


# --- ENH-018: central hosting -------------------------------------------------


async def test_indexes_land_in_the_central_store(tmp_path: Path) -> None:
    ws, central = await _stage_and_index(tmp_path)
    for s in _SERVICES:
        assert (central / repo_key(ws / s) / "meta.json").exists()  # hosted centrally
        assert not (ws / s / ".ckg").exists()  # not in the repo


# --- ENH-018: read-only consumers (sync; main() owns its own loop) ------------


def test_read_only_consumer_cannot_write(tmp_path: Path) -> None:
    ws, _ = _stage(tmp_path)
    orders = ws / "orders"
    assert main(["index", str(orders)]) == 0  # build (writable, central)
    assert main(["index", str(orders), "--read-only"]) == 2  # refused
    assert main(["routes", str(orders), "--read-only"]) == 0  # read still works


# --- ENH-019: cwd discovery ---------------------------------------------------


def test_repo_discovered_from_a_subdir(tmp_path: Path) -> None:
    ws, _ = _stage(tmp_path)
    sub = ws / "orders" / "sub"
    sub.mkdir()
    assert discover_repo_root(sub) == (ws / "orders").resolve()


# --- ENH-020: federation + cross-service tracing ------------------------------


async def test_cross_service_map_spans_python_js_and_openapi(tmp_path: Path) -> None:
    ws, _ = await _stage_and_index(tmp_path)
    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(ws / "workspace.yaml"))
    m = await fed.service_map()

    assert {(e["from_service"], e["to_service"]) for e in m["edges"]} == {
        ("web", "gateway"),  # JS fetch
        ("gateway", "orders"),  # httpx client instance + base_url
        ("orders", "payments"),  # requests → matched to payments' OpenAPI
    }
    # the orders→payments edge is anchored to the contract (no framework handler)
    charge = next(e for e in m["edges"] if e["to_service"] == "payments")
    assert charge["via"] == "openapi" and charge["handler"] == "chargeCard"


async def test_trace_data_flow_and_blast_radius(tmp_path: Path) -> None:
    ws, _ = await _stage_and_index(tmp_path)
    tools = {t.name: t for t in federated_tools(ws / "workspace.yaml")}
    assert {"ckg_services_map", "ckg_trace"} <= set(tools)

    downstream = json.loads(await tools["ckg_trace"].run(service="web"))
    assert downstream["reached"] == ["gateway", "orders", "payments"]  # data flow

    upstream = json.loads(await tools["ckg_trace"].run(service="payments", direction="upstream"))
    assert upstream["reached"] == ["gateway", "orders", "web"]  # blast radius


def test_cli_services_map_and_trace(tmp_path: Path, capsys) -> None:
    ws, _ = _stage(tmp_path)
    for s in _SERVICES:
        assert main(["index", str(ws / s)]) == 0
    wf = str(ws / "workspace.yaml")

    assert main(["services-map", "--workspace", wf]) == 0
    out = capsys.readouterr().out
    assert "web → gateway" in out
    assert "orders → payments" in out and "via=openapi" in out

    assert main(["trace", "web", "--workspace", wf]) == 0
    assert "reached: gateway, orders, payments" in capsys.readouterr().out

    assert main(["trace", "nope", "--workspace", wf]) == 2  # unknown service → clean exit
