"""Config loading (ckg.yaml) — block parsing + YAML-boolean coercion.

Guards BUG-008: YAML 1.1 parses bare ``off``/``on`` as booleans, so the shipped
``rerank: off`` arrived as ``False`` and failed string validation, breaking
``ckg query`` with the default config.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.config import RetrieveConfig

_REPO_ROOT = Path(__file__).resolve().parents[1]


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "ckg.yaml"
    p.write_text(body)
    return p


def test_shipped_ckg_yaml_retrieve_block_loads() -> None:
    """The shipped ckg.yaml must load — it has ``rerank: off`` (a YAML bool)."""
    ckg = _REPO_ROOT / "ckg.yaml"
    assert ckg.exists(), "shipped ckg.yaml not found"
    rc = RetrieveConfig.load(ckg)
    assert rc.rerank == "off"


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
