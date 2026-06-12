"""IngestPipeline directly against a GraphStore: report tally, skipped
propagation, and that the resolver runs as the final pass."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.ingest import IngestPipeline, PackRegistry, RepoSource
from agentforge_graph.ingest.packs.python import PYTHON_PACK
from agentforge_graph.store import KuzuGraphStore


@pytest.fixture
async def store(tmp_path: Path) -> AsyncIterator[KuzuGraphStore]:
    s = await KuzuGraphStore.open(tmp_path / "graph.kuzu")
    try:
        yield s
    finally:
        await s.close()


@pytest.fixture
def registry() -> PackRegistry:
    return PackRegistry([PYTHON_PACK])


async def test_pipeline_indexes_and_resolves(
    store: KuzuGraphStore, registry: PackRegistry, python_repo: Path
) -> None:
    report = await IngestPipeline(repo="r").run(RepoSource(python_repo), store, registry)
    assert report.files_indexed == 2
    assert report.nodes > 0
    assert report.resolve.refs_resolved == 2
    assert report.by_edge_kind.get("CONTAINS", 0) >= 5


async def test_pipeline_skipped_surface_in_report(
    store: KuzuGraphStore, registry: PackRegistry, python_repo: Path
) -> None:
    src = RepoSource(python_repo, max_file_kb=0)  # everything too big
    report = await IngestPipeline(repo="r").run(src, store, registry)
    assert report.files_indexed == 0
    assert len(report.skipped) == 2
    assert report.resolve.refs_resolved == 0  # nothing to resolve


async def test_pipeline_commit_flows_to_provenance(
    store: KuzuGraphStore, registry: PackRegistry, python_repo: Path
) -> None:
    await IngestPipeline(repo="r", commit="abc123").run(RepoSource(python_repo), store, registry)
    from agentforge_graph.core import GraphQuery

    nodes = (await store.query(GraphQuery(limit=10000))).nodes
    code_nodes = [n for n in nodes if n.provenance.source.value == "parsed"]
    assert code_nodes and all(n.provenance.commit == "abc123" for n in code_nodes)
