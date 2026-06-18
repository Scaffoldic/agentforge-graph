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
from pydantic import BaseModel, Field, ValidationError, field_validator

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
    # ENH-003: bedrock | fake | openai | <entry-point>. `openai` also covers
    # OpenAI-compatible local servers via `base_url` (Ollama/vLLM/LM Studio).
    driver: str = "bedrock"
    model: str = "cohere.embed-v4:0"
    region: str = "us-east-1"
    dim: int = 1024
    batch_size: int = 96
    assume_role_arn: str = ""  # set for CI; empty = default AWS credential chain
    base_url: str = ""  # ENH-003: OpenAI-compatible endpoint (empty = provider default)
    api_key_env: str = ""  # ENH-003: env var holding the API key (empty = provider default)


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
    # ENH-009: off (default) | lexical | cross_encoder. `lexical` is a
    # deterministic subtoken blend (helps keyword/symbol-naming queries, mixed on
    # prose). `cross_encoder` is a real semantic re-score via sentence-transformers
    # (the `rerank` extra; lazy-loaded). Both opt-in (measure, don't blind-flip).
    rerank: str = "off"
    rerank_weight: float = 0.5  # final = (1-w)*base + w*signal (overlap | σ(cross))
    rerank_model: str = ""  # cross_encoder model id (empty = a small ms-marco default)
    edge_weights: dict[str, float] = Field(default_factory=_default_edge_weights)

    @field_validator("rerank", mode="before")
    @classmethod
    def _coerce_rerank(cls, v: Any) -> Any:
        # YAML 1.1 parses bare `off`/`on` as booleans, so `rerank: off` (as shipped
        # in ckg.yaml) arrives as False and would fail string validation. Map the
        # booleans back to the canonical modes: off -> disabled, on -> the lexical
        # reranker (the only enabled mode).
        if isinstance(v, bool):
            return "lexical" if v else "off"
        return v


class RepoMapConfig(_Block):
    """The ``repomap:`` block of ckg.yaml (feat-007)."""

    KEY: ClassVar[str] = "repomap"
    default_budget: int = 2000
    damping: float = 0.85
    kinds: list[str] = Field(default_factory=lambda: ["Class", "Function", "Method"])
    edge_weights: dict[str, float] = Field(default_factory=_default_edge_weights)
    # ENH-007: down-weight clearly-private symbols (leading-underscore names or
    # `_`-prefixed modules) so the map surfaces the public API first. A weight,
    # not a filter: private hubs can still appear when genuinely central. In
    # [0, 1]; 0.0 = pure centrality, higher demotes private harder. Private
    # symbols are multiplied by (1 - public_bias).
    public_bias: float = 0.5


class ServeConfig(_Block):
    """The ``serve:`` block of ckg.yaml (feat-008 — MCP server + guardrails)."""

    KEY: ClassVar[str] = "serve"
    transport: str = "stdio"  # feat-008: stdio | http (streamable-HTTP at /mcp)
    host: str = "127.0.0.1"  # http transport bind host
    port: int = 8765  # http transport port
    # ENH-005: bearer token for the HTTP transport (empty = no auth, localhost
    # default). Prefer $CKG_HTTP_AUTH_TOKEN over putting the secret in ckg.yaml.
    http_auth_token: str = ""
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

    Claude runs on **AWS Bedrock** (default) or the **direct Anthropic API**
    (``provider: anthropic`` — ENH-003 phase 2, the non-AWS path). Never runs
    implicitly — only ``ckg enrich`` / ``CodeGraph.enrich()``."""

    KEY: ClassVar[str] = "enrich"
    enabled: bool = True
    # ENH-003: provider for BOTH judge + summarizer. bedrock | anthropic |
    # scripted | <entry-point>. `anthropic` = direct Anthropic API (needs
    # ANTHROPIC_API_KEY); `scripted` is the credential-free deterministic one.
    provider: str = "bedrock"
    # Default is a Bedrock inference-profile id (the `us.` prefix). The
    # `anthropic` provider normalises it to the bare API id automatically.
    model: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    region: str = "us-east-1"
    assume_role_arn: str = ""  # set for CI; empty = default AWS credential chain
    base_url: str = ""  # ENH-003: Anthropic-compatible endpoint (empty = default)
    api_key_env: str = ""  # ENH-003: env var holding the API key (empty = ANTHROPIC_API_KEY)
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

    Reads ``enabled`` + ``adr_globs`` (deterministic pass) and ``infer_budget_usd``
    (the ``ckg enrich --decisions`` LLM matcher's USD cap). ``doc_globs``/
    ``commit_messages`` are declared for follow-ups; ``infer_governs`` is the
    default for the LLM pass (the CLI flag runs it on demand regardless)."""

    KEY: ClassVar[str] = "knowledge"
    enabled: bool = True
    adr_globs: list[str] = Field(default_factory=_default_adr_globs)
    doc_globs: list[str] = Field(default_factory=list)  # general docs → DocChunks+DESCRIBES
    commit_messages: bool = False  # follow-up
    infer_governs: bool = False  # default for the LLM matcher (CLI flag overrides)
    infer_budget_usd: float = 1.0  # USD cap for the infer_governs pass


class TemporalConfig(_Block):
    """The ``temporal:`` block of ckg.yaml (feat-009 — git-evolution layer).

    **Opt-in (default off).** When on (and the source is a git repo), the
    feat-004 refresh records symbol lifecycle into a ``.ckg/temporal.db``
    sidecar — the basis for history / changed-since / as-of and churn ranking
    signals. Off means delete-on-refresh, exactly as before. See
    ``docs/design/design-009-temporal-evolution-layer.md``."""

    KEY: ClassVar[str] = "temporal"
    enabled: bool = False
    history_backfill: int = 0  # commits to replay at first index (chunk 4)
    retention_commits: int = 1000  # prune closed events beyond this horizon (chunk 5)
    rename_detection: str = "file"  # file (exact git renames) | signature (intra-file, chunk 6)
