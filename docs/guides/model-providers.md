# Model providers — pick one, or bring your own

agentforge-graph calls a model in two places:

| Role | What it does | Feature | Selected by |
|---|---|---|---|
| **Embedder** | turns code chunks into vectors for semantic search | feat-005 | `embed.driver` |
| **Pattern judge** + **Summarizer** | confirms design-pattern tags · writes module/repo summaries | feat-012 | `enrich.provider` (one name selects both) |

Every boundary is an **interface** ([`Embedder`](../../src/agentforge_graph/embed/base.py),
[`PatternJudge` / `Summarizer`](../../src/agentforge_graph/enrich/)), resolved by a
**provider registry** (ENH-003) that mirrors the storage-driver registry: a
config name → an adapter, looked up in the built-ins first, then in an
entry-point group. So switching providers — or adding your own — is a config
line, never a core change.

> **Nothing runs in CI.** The deterministic `fake` embedder and `scripted`
> judge/summarizer stand in, so building and testing needs no model and no
> credentials. Live model tests are env-gated.

---

## What ships today (first-party)

| Role | Built-in providers | Install | Credentials |
|---|---|---|---|
| Embedder | `bedrock` (Cohere `embed-v4`) | `--extra bedrock` | AWS creds / assume-role |
| | `openai` (`text-embedding-3-*`, **+ local**) | `--extra openai` | `OPENAI_API_KEY` |
| | `fake` (deterministic, CI/offline) | base | none |
| Judge + Summarizer | `bedrock` (Claude on Bedrock) | `--extra bedrock` | AWS creds / assume-role |
| | `anthropic` (Claude, direct API) | base (SDK bundled) | `ANTHROPIC_API_KEY` |
| | `scripted` (deterministic, CI/offline) | base | none |

The `anthropic` and `bedrock` Claude paths share all prompts, parsing, cost
tracking, and budget rails — only the transport differs
([`enrich/claude.py`](../../src/agentforge_graph/enrich/claude.py) is the shared
core). `bedrock` stays the default so existing deployments are unchanged.

---

## Change your provider (config only)

All keys live in **`ckg.yaml`**. Set the env var, then pick the provider.

### Embeddings → OpenAI

```yaml
embed:
  driver: "openai"
  model: "text-embedding-3-small"   # or text-embedding-3-large
  dim: 1536                         # 3-* models support arbitrary output dims
```
```bash
export OPENAI_API_KEY=sk-...
uv sync --extra engine --extra openai
uv run ckg embed .
```

### Embeddings → a local / self-hosted model (OpenAI-compatible)

Any server that speaks the OpenAI embeddings API — **Ollama, vLLM, LM Studio,
a gateway** — works through the same `openai` driver by pointing `base_url` at it:

```yaml
embed:
  driver: "openai"
  base_url: "http://localhost:11434/v1"   # e.g. Ollama
  model: "nomic-embed-text"
  dim: 768
  api_key_env: "OPENAI_API_KEY"           # many local servers accept any value
```

### Enrichment → direct Anthropic API (no AWS)

```yaml
enrich:
  provider: "anthropic"
  model: "claude-haiku-4-5-20251001"   # bare API id; the Bedrock default is
                                       # auto-normalised, so you can omit this
```
```bash
export ANTHROPIC_API_KEY=sk-ant-...
uv run ckg enrich .
```

`model` may be left at the Bedrock default
(`us.anthropic.claude-haiku-4-5-20251001-v1:0`) — the `anthropic` provider strips
the inference-profile prefix/suffix automatically
([`api_model_id`](../../src/agentforge_graph/enrich/anthropic_client.py)). For an
Anthropic-compatible gateway, set `enrich.base_url` and/or `enrich.api_key_env`.

### Stay fully offline

```yaml
embed:  { driver: "fake" }
enrich: { provider: "scripted" }
```

---

## Bring your own provider (no fork, `pip install` + one line)

A third-party provider is an **out-of-tree package** that registers a builder
under the matching entry-point group. The engine discovers it at runtime — you
never touch agentforge-graph's source.

Entry-point groups:

| Role | Group | Builder signature |
|---|---|---|
| Embedder | `agentforge_graph.embedder_providers` | `(EmbedConfig) -> Embedder` |
| Judge | `agentforge_graph.judge_providers` | `(EnrichConfig) -> PatternJudge` |
| Summarizer | `agentforge_graph.summarizer_providers` | `(EnrichConfig) -> Summarizer` |

### 1. Implement the interface

```python
# my_ckg_cohere/embedder.py
from agentforge_graph.embed.base import Embedder, InputType

class CohereEmbedder(Embedder):
    def __init__(self, model: str, dim: int) -> None:
        self.name = f"cohere:{model}"
        self.model = model
        self.dim = dim

    async def embed(self, texts: list[str], input_type: InputType = "document") -> list[list[float]]:
        ...  # call your API; return one vector per text, each of length self.dim
```

### 2. Expose a builder + register the entry point

```python
# my_ckg_cohere/__init__.py
from agentforge_graph.config import EmbedConfig
from .embedder import CohereEmbedder

def build(cfg: EmbedConfig) -> CohereEmbedder:        # the builder
    return CohereEmbedder(model=cfg.model, dim=cfg.dim)
```

```toml
# my_ckg_cohere/pyproject.toml
[project.entry-points."agentforge_graph.embedder_providers"]
cohere = "my_ckg_cohere:build"
```

### 3. Install and select it

```bash
pip install my-ckg-cohere      # or: uv add my-ckg-cohere
```
```yaml
# ckg.yaml — no agentforge-graph change
embed:
  driver: "cohere"
  model: "embed-english-v3.0"
  dim: 1024
```

That's the whole contract. The judge/summarizer path is identical — implement
[`PatternJudge`](../../src/agentforge_graph/enrich/judge.py) /
[`Summarizer`](../../src/agentforge_graph/enrich/summarizer.py), register under
`…judge_providers` / `…summarizer_providers`, select with `enrich.provider`.

> **Tip:** the cleanest LLM judge/summarizer is a custom `ClaudeClient` (the
> `invoke()` + `cost_usd` duck type in
> [`enrich/claude.py`](../../src/agentforge_graph/enrich/claude.py)) handed to the
> shared `ClaudeJudge` / `ClaudeSummarizer` — you reuse all prompts, parsing,
> cost, and budget rails and only write the transport. That's exactly how the
> first-party Bedrock and Anthropic adapters are built.

### What you get for free

The engine, retrieval, budget breaker, heuristics, taxonomy, and orchestration
are provider-agnostic. A provider supplies **only** the model call. If a config
name matches no built-in and no entry point, resolution raises a `ProviderNotFound`
listing the built-ins and the group to register under.

---

## Verify a provider

```bash
# offline contract check (no creds)
uv run pytest tests/embed/test_openai.py tests/enrich/test_anthropic.py

# live smoke (real calls, env-gated)
CKG_LIVE_OPENAI=1    OPENAI_API_KEY=...     uv run pytest tests/embed/test_openai_live.py
CKG_LIVE_ANTHROPIC=1 ANTHROPIC_API_KEY=...  uv run pytest tests/enrich/test_anthropic_live.py
```

See [`CONTRIBUTING.md`](../../CONTRIBUTING.md) for the full playbook and
[ENH-003](../enhancements/ENH-003-pluggable-model-provider-registry.md) for the
design.
