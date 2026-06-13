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
    incremental: bool = True  # feat-004: re-index only the diff when a prior index exists
    resolve_scope_hops: int = 1  # import-graph hops to re-resolve around a changed file


class ChunkingConfig(_Block):
    """The ``chunking:`` block of ckg.yaml (feat-005 / ADR-0007)."""

    KEY: ClassVar[str] = "chunking"
    max_tokens: int = 512
    min_tokens: int = 64


class EmbedConfig(_Block):
    """The ``embed:`` block of ckg.yaml (feat-005). Default driver is
    ``bedrock`` (Cohere embed-v4); tests/CI use ``fake``."""

    KEY: ClassVar[str] = "embed"
    driver: str = "bedrock"  # bedrock | fake  (fastembed/voyage later)
    model: str = "cohere.embed-v4:0"
    region: str = "us-east-1"
    dim: int = 1024
    batch_size: int = 96
    assume_role_arn: str = ""  # set for CI; empty = default AWS credential chain


def _default_edge_weights() -> dict[str, float]:
    # By provenance: resolved facts outrank parsed; llm is second-class (ADR-0004).
    return {"resolved": 1.0, "manual": 0.8, "parsed": 0.5, "llm": 0.3}


class RetrieveConfig(_Block):
    """The ``retrieve:`` block of ckg.yaml (feat-006 / ADR-0008)."""

    KEY: ClassVar[str] = "retrieve"
    k: int = 8
    depth: int = 1
    decay: float = 0.6
    fanout_cap: int = 25  # max neighbors expanded per hop (overflow noted, not silent)
    rerank: str = "off"  # off | <reranker ref>  (off at 0.1)
    edge_weights: dict[str, float] = Field(default_factory=_default_edge_weights)


class RepoMapConfig(_Block):
    """The ``repomap:`` block of ckg.yaml (feat-007)."""

    KEY: ClassVar[str] = "repomap"
    default_budget: int = 2000
    damping: float = 0.85
    kinds: list[str] = Field(default_factory=lambda: ["Class", "Function", "Method"])
    edge_weights: dict[str, float] = Field(default_factory=_default_edge_weights)


class ServeConfig(_Block):
    """The ``serve:`` block of ckg.yaml (feat-008 — MCP guardrails)."""

    KEY: ClassVar[str] = "serve"
    max_depth: int = 3
    max_k: int = 50
    response_token_cap: int = 6000
    refresh_on_call: bool = False


class FrameworksConfig(_Block):
    """The ``frameworks:`` block of ckg.yaml (feat-011)."""

    KEY: ClassVar[str] = "frameworks"
    # "auto" → detect per repo; "off" → none; or an explicit list of pack names.
    enabled: str | list[str] = "auto"
    packs: list[str] = Field(default_factory=list)  # force-enable, e.g. ["fastapi"]


class EnrichConfig(_Block):
    """The ``enrich:`` block of ckg.yaml (feat-012 — LLM enrichment).

    Anthropic Claude runs on **AWS Bedrock** (same credential path as the Cohere
    embedder); ``model`` is a Bedrock model id. Never runs implicitly — only
    ``ckg enrich`` / ``CodeGraph.enrich()``."""

    KEY: ClassVar[str] = "enrich"
    enabled: bool = True
    # ENH-003: provider for BOTH judge + summarizer. bedrock | scripted |
    # <entry-point>. `scripted` is the credential-free deterministic provider.
    provider: str = "bedrock"
    # Bedrock inference-profile id (the `us.` prefix; on-demand isn't supported
    # for the bare 4.5 model id). Cheap tier.
    model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    region: str = "us-east-1"
    assume_role_arn: str = ""  # set for CI; empty = default AWS credential chain
    budget_usd: float = 2.0  # per-run LLM judge cap (breaker)
    confidence_floor: float = 0.7  # drop tags below this
    taxonomy: str = "v1"
    patterns_recall: str = "conservative"  # ENH-001: conservative | broad
    concurrency: int = 6  # ENH-002: in-flight LLM calls per enrich run
    summary_max_words: int = 120  # feat-012 summaries
    summary_levels: list[str] = Field(default_factory=lambda: ["file", "repo"])


def _default_adr_globs() -> list[str]:
    return ["docs/adr/**/*.md", "docs/decisions/**/*.md"]


class KnowledgeConfig(_Block):
    """The ``knowledge:`` block of ckg.yaml (feat-010 — ADR & docs ingestion).

    MVP reads ``enabled`` + ``adr_globs``; ``doc_globs``/``commit_messages``/
    ``infer_governs``/``infer_budget_usd`` are declared for follow-ups."""

    KEY: ClassVar[str] = "knowledge"
    enabled: bool = True
    adr_globs: list[str] = Field(default_factory=_default_adr_globs)
    doc_globs: list[str] = Field(default_factory=list)  # follow-up: general docs
    commit_messages: bool = False  # follow-up
    infer_governs: bool = False  # follow-up: LLM matcher (off by default)
    infer_budget_usd: float = 1.0
