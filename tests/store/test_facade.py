"""Store facade: config resolution, fail-at-startup paths, and the
vector→graph expand join."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.config import StoreConfig
from agentforge_graph.core import EdgeKind, ScoredRef
from agentforge_graph.core.conformance import make_sample_subgraph
from agentforge_graph.store import (
    DriverNotFound,
    SchemaVersionError,
    Store,
    StoreConfigError,
    graph_driver,
    vector_driver,
)
from agentforge_graph.store.facade import STORE_SCHEMA_VERSION

# --- config -----------------------------------------------------------------


def test_config_defaults_when_absent(tmp_path: Path) -> None:
    cfg = StoreConfig.load(tmp_path / "missing.yaml")
    assert cfg.path == ".ckg"
    assert cfg.graph.driver == "kuzu"
    assert cfg.vectors.driver == "lancedb"
    assert StoreConfig.load(None).path == ".ckg"  # None → defaults too


def test_config_parses_store_block(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text(
        "store:\n  path: .idx\n  graph:\n    driver: kuzu\n  vectors:\n    driver: lancedb\n"
    )
    cfg = StoreConfig.load(y)
    assert cfg.path == ".idx"


def test_config_ignores_unknown_keys(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text("store:\n  path: .idx\n  future_key: 1\ningest:\n  languages: auto\n")
    assert StoreConfig.load(y).path == ".idx"  # lenient: unknown keys ignored


def test_config_rejects_malformed_yaml(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text("store: [unbalanced\n")
    with pytest.raises(StoreConfigError):
        StoreConfig.load(y)


def test_config_rejects_bad_store_block(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text("store:\n  graph: not-a-mapping\n")
    with pytest.raises(StoreConfigError):
        StoreConfig.load(y)


# --- registry ---------------------------------------------------------------


def test_registry_resolves_builtins() -> None:
    from agentforge_graph.store import KuzuGraphStore, LanceVectorStore

    assert graph_driver("kuzu") is KuzuGraphStore
    assert vector_driver("lancedb") is LanceVectorStore


def test_registry_unknown_driver_raises() -> None:
    with pytest.raises(DriverNotFound, match="bogus"):
        graph_driver("bogus")
    with pytest.raises(DriverNotFound):
        vector_driver("nope")


# --- facade open / fail-at-startup ------------------------------------------


async def test_open_defaults_creates_ckg(tmp_path: Path) -> None:
    store = await Store.open(repo_path=tmp_path)
    try:
        assert (tmp_path / ".ckg" / "meta.json").exists()
        assert (tmp_path / ".ckg" / "graph.kuzu").exists()
        await store.graph.upsert(make_sample_subgraph())
        got = await store.graph.get(make_sample_subgraph().nodes[0].id)
        assert got is not None
    finally:
        await store.close()


async def test_open_unknown_driver_fails_at_startup(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text("store:\n  graph:\n    driver: nosuchdb\n")
    with pytest.raises(DriverNotFound):
        await Store.open(repo_path=tmp_path, config=y)


async def test_open_schema_mismatch_fails_at_startup(tmp_path: Path) -> None:
    root = tmp_path / ".ckg"
    root.mkdir()
    (root / "meta.json").write_text(json.dumps({"schema_version": STORE_SCHEMA_VERSION + 99}))
    with pytest.raises(SchemaVersionError):
        await Store.open(repo_path=tmp_path)


async def test_open_reuses_existing_meta(tmp_path: Path) -> None:
    s1 = await Store.open(repo_path=tmp_path)
    await s1.close()
    s2 = await Store.open(repo_path=tmp_path)  # meta.json exists, version matches
    await s2.close()


# --- expand (vector -> graph join) ------------------------------------------


async def test_expand_joins_vector_hit_into_graph(tmp_path: Path) -> None:
    store = await Store.open(repo_path=tmp_path)
    try:
        sg = make_sample_subgraph()
        await store.graph.upsert(sg)
        file_id, class_id, method_id = (n.id for n in sg.nodes)
        # a vector hit on the class expands to its CONTAINS neighborhood
        result = await store.expand(
            [ScoredRef(ref=class_id, score=1.0)], kinds=[EdgeKind.CONTAINS], depth=1
        )
        ids = {n.id for n in result.nodes}
        assert class_id in ids  # the hit itself
        assert file_id in ids and method_id in ids  # one-hop neighbors
    finally:
        await store.close()


async def test_expand_skips_absent_ref(tmp_path: Path) -> None:
    store = await Store.open(repo_path=tmp_path)
    try:
        ghost = make_sample_subgraph().nodes[0].id
        result = await store.expand([ScoredRef(ref=ghost, score=1.0)])
        assert result.nodes == []  # nothing in the graph yet
    finally:
        await store.close()
