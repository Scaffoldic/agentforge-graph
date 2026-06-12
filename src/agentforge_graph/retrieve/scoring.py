"""Scoring math for retrieval: provenance edge weights, per-hop decay, and
dedupe (max score wins, why-traces unioned)."""

from __future__ import annotations

from agentforge_graph.core import Source

from .pack import ContextItem


def edge_weight(weights: dict[str, float], source: Source) -> float:
    """Weight an expansion edge by its provenance — resolved > parsed > llm
    (ADR-0004). Unknown sources fall back to 0.5."""
    return weights.get(source.value, 0.5)


def step_score(parent_score: float, decay: float, weight: float) -> float:
    """One hop of decay: ``parent × decay × edge_weight``. Repeated over hops
    yields the ``decay^hop`` falloff."""
    return parent_score * decay * weight


def dedupe_max(items: list[ContextItem]) -> list[ContextItem]:
    """Collapse items sharing an id to the highest-scoring one, unioning the
    why-traces; return sorted by score descending."""
    best: dict[str, ContextItem] = {}
    whys: dict[str, list[str]] = {}
    for it in items:
        acc = whys.setdefault(it.id, [])
        for w in it.why:
            if w not in acc:
                acc.append(w)
        if it.id not in best or it.score > best[it.id].score:
            best[it.id] = it
    merged = [it.model_copy(update={"why": whys[i]}) for i, it in best.items()]
    return sorted(merged, key=lambda i: i.score, reverse=True)
