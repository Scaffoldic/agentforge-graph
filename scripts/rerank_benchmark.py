"""ENH-013 rigorous rerank benchmark (out-of-package; needs creds, not CI).

A CodeSearchNet-style natural-language → code retrieval benchmark with
**objective, auto-generated labels**: each documented symbol's docstring is the
query and that symbol is the gold answer (pairs come straight from the engine's
``DocChunk --DESCRIBES--> symbol`` edges). Verified leakage-free — the engine
embeds code chunks *without* their docstrings, and we search the **code-chunk
vectors only** (``filter={"kind": "Chunk"}``), so the docstring query never
trivially matches its own doc chunk and the doc-seeding retrieval path is
bypassed. This isolates the reranker's contribution to pure NL→code matching.

For each query we take a candidate pool of code chunks (vector top-N), mark a
chunk relevant when it overlaps the gold symbol's span in the same file, and
compare the **base** order (cosine) with a **Bedrock-reranked** order at blend
weights. We report recall@k / MRR over many queries across several repos, a
**paired bootstrap** significance test on the per-query reciprocal-rank delta,
and **p50/p95** Bedrock rerank latency.

Usage:
    uv run python scripts/rerank_benchmark.py --repo /tmp/click --repo /tmp/httpx --cap 100
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from dataclasses import dataclass, field

from agentforge_graph.config import EmbedConfig, RetrieveConfig
from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.embed import embedder_from_config
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.retrieve.rerank import BedrockRerankScorer

POOL = 30  # code-chunk candidate pool per query
KS = (1, 5, 10)
WEIGHTS = (0.3, 0.5, 0.7)
BOOTSTRAP = 2000
_SEED = 1234567  # deterministic LCG seed (no Math.random / Date in env)
_MAX_QUERY = 400  # truncate long docstrings for the query/rerank payload


@dataclass
class QueryResult:
    rr_base: float
    rr: dict[float, float] = field(default_factory=dict)  # weight -> reciprocal rank
    hit_base: dict[int, int] = field(default_factory=dict)  # k -> 0/1
    hit: dict[float, dict[int, int]] = field(default_factory=dict)
    latency: float = 0.0
    gold_in_pool: bool = True


def _overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    if not a or not b:
        return False
    return not (a[1] < b[0] or a[0] > b[1])


def _rr(flags: list[int]) -> float:
    for i, f in enumerate(flags):
        if f:
            return 1.0 / (i + 1)
    return 0.0


def _hits(flags: list[int]) -> dict[int, int]:
    return {k: (1 if any(flags[:k]) else 0) for k in KS}


def _order(scores: list[float]) -> list[int]:
    return sorted(range(len(scores)), key=lambda i: -scores[i])


async def _load_pairs(cg: CodeGraph, cap: int) -> list[tuple[str, str, tuple[int, int]]]:
    """(query_docstring, gold_path, gold_span) from DocChunk->DESCRIBES->symbol,
    deterministically sampled to ``cap`` (evenly strided over sorted ids)."""
    g = cg.store.graph
    docs = (await g.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=10_000_000))).nodes
    pairs: list[tuple[str, str, tuple[int, int]]] = []
    for d in sorted(docs, key=lambda n: n.id):
        text = (d.attrs.get("text") or "").strip()
        if len(text) < 20:
            continue
        for e in await g.adjacent(d.id, [EdgeKind.DESCRIBES], "out"):
            tgt = await g.get(e.dst)
            if (
                tgt
                and tgt.kind in (NodeKind.FUNCTION, NodeKind.METHOD, NodeKind.CLASS)
                and tgt.span
            ):
                pairs.append((text[:_MAX_QUERY], SymbolID.parse(tgt.id).path, tgt.span))
                break
    if len(pairs) <= cap:
        return pairs
    stride = len(pairs) / cap
    return [pairs[int(i * stride)] for i in range(cap)]


async def _bench_repo(cg: CodeGraph, scorer: BedrockRerankScorer, cap: int) -> list[QueryResult]:
    pairs = await _load_pairs(cg, cap)
    emb = embedder_from_config(EmbedConfig.load(None))
    qvecs = await emb.embed([q for q, _, _ in pairs], "query")
    out: list[QueryResult] = []
    for (query, gpath, gspan), qv in zip(pairs, qvecs, strict=True):
        hits = await cg.store.vectors.search(qv, POOL, filter={"kind": NodeKind.CHUNK.value})
        nodes = [await cg.store.graph.get(h.ref) for h in hits]
        cand = [(h, n) for h, n in zip(hits, nodes, strict=True) if n is not None]
        if not cand:
            continue
        base_scores = [h.score for h, _ in cand]
        flags = [
            1 if (SymbolID.parse(n.id).path == gpath and _overlap(n.span, gspan)) else 0
            for _, n in cand
        ]
        r = QueryResult(rr_base=0.0, gold_in_pool=any(flags))
        base_ord = _order(base_scores)
        bf = [flags[i] for i in base_ord]
        r.rr_base = _rr(bf)
        r.hit_base = _hits(bf)
        t0 = time.perf_counter()
        logits = scorer.score(query, [(n.attrs.get("code") or n.name)[:2000] for _, n in cand])
        r.latency = time.perf_counter() - t0
        relevance = [1.0 / (1.0 + math.exp(-x)) for x in logits]
        for w in WEIGHTS:
            blended = [(1 - w) * b + w * rel for b, rel in zip(base_scores, relevance, strict=True)]
            o = _order(blended)
            wf = [flags[i] for i in o]
            r.rr[w] = _rr(wf)
            r.hit[w] = _hits(wf)
        out.append(r)
    return out


def _bootstrap_ci(deltas: list[float]) -> tuple[float, float, float, float]:
    """Mean delta + 95% CI + one-sided p (fraction of resamples <= 0) via a
    deterministic LCG paired bootstrap."""
    n = len(deltas)
    mean = sum(deltas) / n if n else 0.0
    state = _SEED
    means: list[float] = []
    for _ in range(BOOTSTRAP):
        s = 0.0
        for _ in range(n):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            s += deltas[state % n]
        means.append(s / n)
    means.sort()
    lo = means[int(0.025 * BOOTSTRAP)]
    hi = means[int(0.975 * BOOTSTRAP)]
    p = sum(1 for m in means if m <= 0) / BOOTSTRAP
    return mean, lo, hi, p


def _pct(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, int(q * len(s)))]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--cap", type=int, default=100)
    ap.add_argument("--model", default="cohere.rerank-v3-5:0")
    args = ap.parse_args()

    rcfg = RetrieveConfig.load(None)
    scorer = BedrockRerankScorer(model=args.model, region=rcfg.rerank_region)
    per_repo: dict[str, list[QueryResult]] = {}
    for repo in args.repo:
        cg = await CodeGraph.open(repo_path=repo)
        try:
            res = await _bench_repo(cg, scorer, args.cap)
        finally:
            await cg.close()
        per_repo[repo] = res
        print(f"  {repo}: {len(res)} queries, gold-in-pool {sum(r.gold_in_pool for r in res)}")

    allr = [r for res in per_repo.values() for r in res]
    _report(per_repo, allr, args)


def _mrr(rs: list[float]) -> float:
    return sum(rs) / len(rs) if rs else 0.0


def _report(
    per_repo: dict[str, list[QueryResult]], allr: list[QueryResult], args: argparse.Namespace
) -> None:
    print(
        f"\nENH-013 rerank BENCHMARK — model={args.model} repos={len(per_repo)} queries={len(allr)}"
    )
    lat = [r.latency for r in allr]
    print(f"rerank latency: p50={1000 * _pct(lat, 0.5):.0f}ms p95={1000 * _pct(lat, 0.95):.0f}ms\n")

    def row(label: str, rs: list[QueryResult]) -> None:
        base_mrr = _mrr([r.rr_base for r in rs])
        cells = [f"{base_mrr:.3f}"]
        for w in WEIGHTS:
            cells.append(f"{_mrr([r.rr[w] for r in rs]):.3f}")
        r1 = sum(r.hit_base[1] for r in rs) / len(rs)
        r1w = sum(r.hit[0.3][1] for r in rs) / len(rs)
        print(f"{label:<22}{'  '.join(f'{c:>7}' for c in cells)}    r@1 {r1:.3f}->{r1w:.3f}")

    print(f"{'corpus':<22}{'baseMRR':>7}  {'w=0.3':>7}  {'w=0.5':>7}  {'w=0.7':>7}")
    print("-" * 64)
    for repo, rs in per_repo.items():
        if rs:
            row(repo.split("/")[-1], rs)
    print("-" * 64)
    row("POOLED", allr)

    deltas = [r.rr[0.3] - r.rr_base for r in allr]
    mean, lo, hi, p = _bootstrap_ci(deltas)
    print(
        f"\nΔMRR (bedrock w=0.3 − base), paired bootstrap n={len(deltas)}:"
        f"\n  mean {mean:+.3f}  95% CI [{lo:+.3f}, {hi:+.3f}]  one-sided p={p:.4f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
