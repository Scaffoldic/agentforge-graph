"""Shared ingest fixtures: the committed Python sample repo and a registry."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.ingest import PackRegistry
from agentforge_graph.ingest.packs.python import PYTHON_PACK

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def python_repo() -> Path:
    return FIXTURES / "python"


@pytest.fixture
def registry() -> PackRegistry:
    return PackRegistry([PYTHON_PACK])
