"""Config loading — block parsing, YAML-boolean coercion, the ``app:`` wrapper
(agentforge.yaml) vs a standalone ckg.yaml, and config discovery.

Guards BUG-008: YAML 1.1 parses bare ``off``/``on`` as booleans, so the shipped
``rerank: off`` arrived as ``False`` and failed string validation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.config import (
    EmbedConfig,
    ResolvedConfig,
    RetrieveConfig,
    StoreConfig,
    block_keys,
    resolve_config,
)
from agentforge_graph.store.errors import StoreConfigError

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, body: str, name: str = "ckg.yaml") -> Path:
    p = tmp_path / name
    p.write_text(body)
    return p


def test_shipped_agentforge_yaml_app_block_loads() -> None:
    """The shipped agentforge.yaml carries the engine config under ``app:`` and
    must load — including ``retrieve.rerank: off`` (a YAML bool)."""
    af = _REPO_ROOT / "agentforge.yaml"
    assert af.exists(), "shipped agentforge.yaml not found"
    assert RetrieveConfig.load(af).rerank == "off"
    assert StoreConfig.load(af).path == ".ckg"
    assert EmbedConfig.load(af).driver == "bedrock"


def test_app_wrapper_vs_top_level(tmp_path: Path) -> None:
    """A block is read from ``app:`` when present, else from the top level."""
    wrapped = _write(
        tmp_path, "agent:\n  name: x\napp:\n  retrieve:\n    k: 11\n", "agentforge.yaml"
    )
    assert RetrieveConfig.load(wrapped).k == 11
    flat = _write(tmp_path, "retrieve:\n  k: 7\n", "ckg.yaml")
    assert RetrieveConfig.load(flat).k == 7


def test_discovery_prefers_agentforge_app_then_ckg(tmp_path: Path) -> None:
    # nothing → None (built-in defaults)
    assert resolve_config(None, tmp_path) is None
    # agentforge.yaml WITHOUT app: + ckg.yaml → ckg.yaml wins (no regression)
    (tmp_path / "agentforge.yaml").write_text("agent:\n  name: x\n")
    (tmp_path / "ckg.yaml").write_text("store:\n  path: from_ckg\n")
    assert resolve_config(None, tmp_path).name == "ckg.yaml"
    # add an app: section → the framework file now wins
    (tmp_path / "agentforge.yaml").write_text(
        "agent:\n  name: x\napp:\n  store:\n    path: from_app\n"
    )
    assert resolve_config(None, tmp_path).name == "agentforge.yaml"
    # an explicit path always wins over discovery
    explicit = tmp_path / "ckg.yaml"
    assert resolve_config(explicit, tmp_path) == explicit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("off", "off"),  # YAML bool False -> disabled
        ("on", "lexical"),  # YAML bool True -> the only enabled mode
        ("lexical", "lexical"),  # explicit string
        ('"off"', "off"),  # explicitly quoted string
        ("false", "off"),  # YAML bool False (alt spelling)
        ("true", "lexical"),  # YAML bool True (alt spelling)
    ],
)
def test_rerank_accepts_yaml_booleans_and_strings(
    tmp_path: Path, value: str, expected: str
) -> None:
    cfg = _write(tmp_path, f"retrieve:\n  rerank: {value}\n")
    assert RetrieveConfig.load(cfg).rerank == expected


def test_rerank_default_is_off(tmp_path: Path) -> None:
    cfg = _write(tmp_path, "retrieve:\n  k: 8\n")
    assert RetrieveConfig.load(cfg).rerank == "off"


# --- ENH-022: ResolvedConfig as a polymorphic config source -----------------


def test_resolved_config_reads_blocks_in_memory() -> None:
    """A block loads from a ResolvedConfig section exactly like from a file."""
    rc = ResolvedConfig(section={"store": {"path": "x"}, "retrieve": {"k": 5}})
    assert StoreConfig.load(rc).path == "x"
    assert RetrieveConfig.load(rc).k == 5


def test_resolved_config_missing_block_is_defaults() -> None:
    rc = ResolvedConfig(section={"store": {"path": "x"}})
    assert RetrieveConfig.load(rc).k == RetrieveConfig().k  # absent → defaults


def test_resolve_config_passes_resolved_through() -> None:
    rc = ResolvedConfig(section={})
    assert resolve_config(rc) is rc  # already merged — nothing to discover


def test_resolved_config_invalid_block_errors_with_origin() -> None:
    rc = ResolvedConfig(section={"retrieve": {"k": "not-an-int"}}, origin="workspace:org:web")
    with pytest.raises(StoreConfigError, match="workspace:org:web"):
        RetrieveConfig.load(rc)


def test_block_keys_covers_known_blocks() -> None:
    keys = block_keys()
    assert {"store", "embed", "retrieve", "ingest", "serve", "enrich"} <= keys
    assert "" not in keys  # the _Block base (empty KEY) is excluded
