"""Pack ranked symbols into a token budget, grouped by file (files ordered by
their top symbol's rank). Whole signature lines only; a final note reports how
many symbols fell below the budget — never a silent cap."""

from __future__ import annotations

from agentforge_graph.chunking import estimate_tokens

from .rank import RankedSymbol


def render_map(ranked: list[RankedSymbol], budget_tokens: int) -> str:
    by_file: dict[str, list[RankedSymbol]] = {}
    order: list[str] = []
    for r in ranked:
        if r.path not in by_file:
            by_file[r.path] = []
            order.append(r.path)
        by_file[r.path].append(r)

    lines: list[str] = []
    emitted = 0
    full = False

    def fits(extra: list[str]) -> bool:
        # measure the whole accumulated content (estimate_tokens is non-additive)
        return estimate_tokens("\n".join(lines + extra)) <= budget_tokens

    for path in order:
        if full:
            break
        header = f"{path}:"
        started = False
        for r in by_file[path]:
            line = f"  {r.signature or f'{r.name}(...)'}"
            trial = [line] if started else [header, line]
            if not fits(trial):
                full = True
                break
            lines.extend(trial)
            started = True
            emitted += 1

    remaining = len(ranked) - emitted
    if remaining > 0:
        lines.append(f"… {remaining} more symbols below the budget")
    return "\n".join(lines)
