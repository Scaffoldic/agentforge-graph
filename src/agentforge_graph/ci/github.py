"""feat-014: the GitHub Actions workflow template for central indexing.

Renders a **self-contained** workflow — ``pip install agentforge-graph`` +
``ckg index`` against the repo's configured (central) store — triggered on
push-to-``main``, a nightly cron, and manual dispatch, with a ``concurrency``
group so exactly one indexing job writes the shared store at a time. A
separately-versioned ``ckg-index-action`` is out of scope (feat-014 §6); this
ships today with no external action to publish first.
"""

from __future__ import annotations

MARKER = "# managed-by: agentforge-graph (ckg ci init)"
WORKFLOW_REL_PATH = ".github/workflows/ckg-index.yml"


def render_workflow(
    *,
    mode: str = "incremental",
    embed: bool = True,
    enrich: bool = False,
    extras: list[str] | None = None,
) -> str:
    """Render the workflow YAML. ``mode`` ``full`` forces a full re-index;
    ``incremental`` (default) refreshes only the diff since the last indexed
    commit. ``extras`` are PyPI extras to install (e.g. ``["bedrock"]`` for
    server-side embeddings)."""
    if mode not in ("incremental", "full"):
        raise ValueError(f"mode must be 'incremental' or 'full', got {mode!r}")
    spec = "agentforge-graph"
    if extras:
        spec = f"agentforge-graph[{','.join(extras)}]"
    full_flag = " --full" if mode == "full" else ""
    steps = [f"          ckg index .{full_flag}"]
    if embed:
        steps.append("          ckg embed .")
    if enrich:
        steps.append("          ckg enrich .")
    index_block = "\n".join(steps)
    return f"""{MARKER} — safe to edit; re-run `ckg ci init --force` to regenerate.
name: CKG central index

# Deterministic, single-writer freshness for the shared/central index
# (store.central_root). CI is the ONLY writer — developers' machines never write
# the central store (that split is enforced by `ckg watch`). See feat-014.

on:
  push:
    branches: [main]
  schedule:
    - cron: "0 3 * * *"   # nightly safety net
  workflow_dispatch: {{}}

concurrency:
  group: ckg-central-index      # one writer at a time — no central write races
  cancel-in-progress: false

permissions:
  contents: read

jobs:
  index:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0        # full history so the temporal layer can seed

      - uses: actions/setup-python@v6
        with:
          python-version: "3.13"

      - name: Install agentforge-graph
        run: pip install "{spec}"

      # Point at the shared/central store and provide provider creds via repo
      # secrets. Configure the store in the committed agentforge.yaml
      # (store.central_root + graph/vectors backend), or via the env below.
      - name: Index into the central store ({mode})
        env:
          CKG_CENTRAL_STORE_URL: ${{{{ secrets.CKG_CENTRAL_STORE_URL }}}}
          # e.g. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY for Bedrock embeddings,
          # or OPENAI_API_KEY — add whatever your embed/enrich provider needs.
        run: |
{index_block}
"""
