"""ENH-013 rerank measurement harness (out-of-package; needs creds, not CI).

Indexes a repo once (Bedrock embed), then for each labelled query retrieves a
single candidate pool and compares the **base** order (cosine + graph) against a
**Bedrock-reranked** order at several blend weights — recall@k / MRR / nDCG@k +
latency. One Bedrock Rerank call per query (the weights re-blend the same
relevance scores in-process), so the campaign is cheap.

Usage:
    uv run python scripts/rerank_eval.py --repo <path> --golden docs/validation/rerank/<set>.yaml

The golden set is YAML: a list of {q: "<query>", relevant: ["<id substring>", …]}.
A retrieved item counts as relevant when any substring occurs in its node id
(case-insensitive) — ids embed path + descriptor, so "Retriever#" or
"retriever.py" both work.
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from pathlib import Path
from typing import Any

import yaml

from agentforge_graph.config import EmbedConfig, RetrieveConfig
from agentforge_graph.embed import embedder_from_config
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.retrieve import Retriever
from agentforge_graph.retrieve.rerank import BedrockRerankScorer, NoopReranker, _candidate_text

POOL = 20  # candidate pool retrieved per query (vector top-k + graph expansion)
KS = (5, 8, 16)
WEIGHTS = (0.3, 0.5, 0.7)


def _relevant(item_id: str, golden: list[str]) -> bool:
    low = item_id.lower()
    return any(g.lower() in low for g in golden)


def _dcg(rels: list[int]) -> float:
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


def _ndcg(order: list[int], n: int) -> float:
    rels = order[:n]
    ideal = sorted(order, reverse=True)[:n]
    idcg = _dcg(ideal)
    return _dcg(rels) / idcg if idcg else 0.0


def _metrics(order_rel: list[int]) -> dict[str, float]:
    """order_rel: 1/0 relevance flags in ranked order. recall@k = hit-rate
    (≥1 relevant in top-k), MRR over the first relevant, nDCG@k."""
    total = sum(order_rel)
    out: dict[str, float] = {}
    for k in KS:
        out[f"recall@{k}"] = 1.0 if any(order_rel[:k]) else 0.0
    rr = 0.0
    for i, r in enumerate(order_rel):
        if r:
            rr = 1.0 / (i + 1)
            break
    out["mrr"] = rr
    out["ndcg@8"] = _ndcg(order_rel, 8) if total else 0.0
    return out


def _blend(base: list[float], relevance: list[float], w: float) -> list[int]:
    """Return relevance flags reordered by the blended score (caller maps via the
    same index list). Here we just return the argsort order indices."""
    blended = [(1 - w) * b + w * r for b, r in zip(base, relevance, strict=True)]
    return sorted(range(len(blended)), key=lambda i: -blended[i])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--golden", required=True)
    ap.add_argument("--config", default=None)
    ap.add_argument("--model", default="cohere.rerank-v3-5:0")
    ap.add_argument("--reindex", action="store_true")
    args = ap.parse_args()

    golden: list[dict[str, Any]] = yaml.safe_load(Path(args.golden).read_text())
    cg = (
        await CodeGraph.index(repo_path=args.repo, config=args.config)
        if args.reindex
        else await CodeGraph.open(repo_path=args.repo, config=args.config)
    )
    emb = embedder_from_config(EmbedConfig.load(args.config))
    rcfg = RetrieveConfig.load(args.config)
    retriever = Retriever(cg.store, emb, rcfg, reranker=NoopReranker())
    scorer = BedrockRerankScorer(model=args.model, region=rcfg.rerank_region)

    configs = ["base", *(f"bedrock w={w}" for w in WEIGHTS)]
    agg: dict[str, dict[str, float]] = {c: {} for c in configs}
    latency: list[float] = []
    n = 0

    for case in golden:
        q, rel = case["q"], case["relevant"]
        pack = await retriever.retrieve(query=q, k=POOL)
        items = pack.items
        if not items:
            print(f"  ! no candidates for {q!r}")
            continue
        n += 1
        base_scores = [it.score for it in items]
        flags = [1 if _relevant(it.id, rel) else 0 for it in items]
        if not any(flags):
            print(f"  ? golden not in pool for {q!r} (rel={rel})")

        # base order = as returned (already score-sorted)
        _accumulate(agg["base"], _metrics(flags))
        # one Bedrock call; blend at each weight
        t0 = time.perf_counter()
        logits = scorer.score(q, [_candidate_text(it) for it in items])
        latency.append(time.perf_counter() - t0)
        relevance = [1.0 / (1.0 + math.exp(-x)) for x in logits]
        for w in WEIGHTS:
            order = _blend(base_scores, relevance, w)
            _accumulate(agg[f"bedrock w={w}"], _metrics([flags[i] for i in order]))

    await cg.close()
    _report(agg, configs, n, latency, args)


def _accumulate(acc: dict[str, float], m: dict[str, float]) -> None:
    for k, v in m.items():
        acc[k] = acc.get(k, 0.0) + v


def _report(
    agg: dict[str, dict[str, float]],
    configs: list[str],
    n: int,
    latency: list[float],
    args: argparse.Namespace,
) -> None:
    cols = [f"recall@{k}" for k in KS] + ["mrr", "ndcg@8"]
    print(f"\nENH-013 rerank eval — repo={args.repo} model={args.model} queries={n}")
    print(
        f"mean Bedrock rerank latency: {1000 * sum(latency) / max(1, len(latency)):.0f} ms/query\n"
    )
    header = f"{'config':<14}" + "".join(f"{c:>10}" for c in cols)
    print(header)
    print("-" * len(header))
    for c in configs:
        row = f"{c:<14}" + "".join(f"{agg[c].get(col, 0.0) / max(1, n):>10.3f}" for col in cols)
        print(row)


if __name__ == "__main__":
    asyncio.run(main())
