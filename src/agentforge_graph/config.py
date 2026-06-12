"""Typed reader for ``ckg.yaml`` — this agent's *own* engine config (NOT
the framework's ``agentforge.yaml``, which has a strict validator).

Unlike the framework file, ours is intentionally lenient: unknown keys are
ignored (``extra='ignore'``) so a config written for a later feature still
loads for an earlier one. Only the ``store:`` block is modelled today;
ingest/chunking/retrieve/… sections gain their own models as those
features land.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError


class GraphCfg(BaseModel):
    driver: str = "kuzu"
    config: dict[str, Any] = Field(default_factory=dict)


class VectorCfg(BaseModel):
    driver: str = "lancedb"
    config: dict[str, Any] = Field(default_factory=dict)


class StoreConfig(BaseModel):
    """The ``store:`` block of ckg.yaml (ADR-0006)."""

    path: str = ".ckg"
    graph: GraphCfg = Field(default_factory=GraphCfg)
    vectors: VectorCfg = Field(default_factory=VectorCfg)

    @classmethod
    def load(cls, ckg_yaml: str | Path | None = None) -> StoreConfig:
        """Parse the ``store:`` block from ``ckg.yaml``. A missing path (or
        ``None``) yields all-default embedded config; malformed YAML or a
        malformed block raises ``StoreConfigError`` (fail-at-startup)."""
        # Imported lazily to avoid an import cycle (store.facade imports this).
        from agentforge_graph.store.errors import StoreConfigError

        if ckg_yaml is None:
            return cls()
        p = Path(ckg_yaml)
        if not p.exists():
            return cls()
        try:
            data = yaml.safe_load(p.read_text()) or {}
        except yaml.YAMLError as exc:
            raise StoreConfigError(f"could not parse {p}: {exc}") from exc
        try:
            return cls.model_validate(data.get("store") or {})
        except ValidationError as exc:
            raise StoreConfigError(f"invalid store config in {p}: {exc}") from exc
