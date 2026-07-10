"""feat-016 chunk 1: the docgen: config block."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from agentforge_graph.config import DocGenConfig, block_keys


def test_defaults() -> None:
    c = DocGenConfig.load(None)
    assert c.output_root == "docs/_generated"
    assert c.types == ["ai-context", "architecture", "component", "design"]
    assert c.ai_context_targets == ["CLAUDE.md", "AGENTS.md"]
    assert c.component_granularity == "package"
    assert c.require_citations is True
    assert c.round_trip is False
    assert c.promote_required is True
    assert c.budget_usd == 5.0
    assert c.max_iterations == 12
    assert c.provider == "anthropic"
    assert c.model_ref() == "anthropic:claude-haiku-4-5"


def test_parses_block(tmp_path: Path) -> None:
    y = tmp_path / "ckg.yaml"
    y.write_text(
        "docgen:\n"
        "  output_root: docs/auto\n"
        "  types: [architecture]\n"
        "  round_trip: true\n"
        "  budget_usd: 2.5\n"
        "  provider: scripted\n"
    )
    c = DocGenConfig.load(y)
    assert c.output_root == "docs/auto"
    assert c.enabled_types() == ["architecture"]
    assert c.round_trip is True
    assert c.budget_usd == 2.5
    assert c.provider == "scripted"


def test_component_granularity_validated() -> None:
    DocGenConfig(component_granularity="hybrid")  # ok
    with pytest.raises(ValidationError):
        DocGenConfig(component_granularity="nonsense")


def test_block_key_discovered() -> None:
    assert "docgen" in block_keys()
