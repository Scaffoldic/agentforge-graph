"""Typed reader for ``ckg.yaml`` — this agent's *own* engine config (NOT
the framework's ``agentforge.yaml``, which has a strict validator).

Unlike the framework file, ours is intentionally lenient: unknown keys are
ignored (``extra='ignore'``) so a config written for a later feature still
loads for an earlier one. The ``store:`` (feat-003) and ``ingest:``
(feat-002) blocks are modelled today; chunking/retrieve/… sections gain
their own models as those features land.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar, Self

import yaml
from pydantic import BaseModel, Field, ValidationError

# Default directories excluded from ingestion (mirrors ckg.yaml's ingest.exclude).
DEFAULT_EXCLUDES = [
    "**/node_modules/**",
    "**/.venv/**",
    "**/dist/**",
    "**/.git/**",
    "**/.ckg/**",
]


def _read_block[T: _Block](model: type[T], key: str, ckg_yaml: str | Path | None) -> T:
    """Parse one top-level block of ckg.yaml into ``model``. Missing file or
    ``None`` → defaults; malformed YAML / block → ``StoreConfigError``."""
    # Imported lazily to avoid an import cycle (store.facade imports this).
    from agentforge_graph.store.errors import StoreConfigError

    if ckg_yaml is None:
        return model()
    p = Path(ckg_yaml)
    if not p.exists():
        return model()
    try:
        data = yaml.safe_load(p.read_text()) or {}
    except yaml.YAMLError as exc:
        raise StoreConfigError(f"could not parse {p}: {exc}") from exc
    try:
        return model.model_validate(data.get(key) or {})
    except ValidationError as exc:
        raise StoreConfigError(f"invalid {key} config in {p}: {exc}") from exc


class _Block(BaseModel):
    """Base for a ckg.yaml section that knows its top-level key."""

    KEY: ClassVar[str] = ""

    @classmethod
    def load(cls, ckg_yaml: str | Path | None = None) -> Self:
        return _read_block(cls, cls.KEY, ckg_yaml)


class GraphCfg(BaseModel):
    driver: str = "kuzu"
    config: dict[str, Any] = Field(default_factory=dict)


class VectorCfg(BaseModel):
    driver: str = "lancedb"
    config: dict[str, Any] = Field(default_factory=dict)


class StoreConfig(_Block):
    """The ``store:`` block of ckg.yaml (ADR-0006)."""

    KEY: ClassVar[str] = "store"
    path: str = ".ckg"
    graph: GraphCfg = Field(default_factory=GraphCfg)
    vectors: VectorCfg = Field(default_factory=VectorCfg)


class IngestConfig(_Block):
    """The ``ingest:`` block of ckg.yaml (feat-002 / ADR-0009)."""

    KEY: ClassVar[str] = "ingest"
    languages: str | list[str] = "auto"  # "auto" or an explicit list of pack names
    exclude: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUDES))
    max_file_kb: int = 512
    lsp_assist: bool = False  # opt-in resolution escalation (Tier B); inert at 0.1
