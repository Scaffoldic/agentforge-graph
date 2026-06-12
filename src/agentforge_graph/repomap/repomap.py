"""``RepoMap`` facade: ranked symbols (structured) + a budget-packed text map."""

from __future__ import annotations

from collections.abc import Sequence

from agentforge_graph.config import RepoMapConfig
from agentforge_graph.core import NodeKind
from agentforge_graph.store import Store

from .rank import RankedSymbol, rank_symbols
from .render import render_map


class RepoMap:
    def __init__(self, store: Store, config: RepoMapConfig) -> None:
        self.store = store
        self.config = config

    def _kinds(self, override: list[NodeKind] | None) -> list[NodeKind]:
        return override if override is not None else [NodeKind(k) for k in self.config.kinds]

    async def ranked_symbols(
        self, k: int = 100, focus: Sequence[str] | None = None
    ) -> list[RankedSymbol]:
        ranked = await rank_symbols(
            self.store, self._kinds(None), self.config.damping, self.config.edge_weights, focus
        )
        return ranked[:k]

    async def render(
        self,
        budget_tokens: int | None = None,
        focus: Sequence[str] | None = None,
        scope: str | None = None,
        kinds: list[NodeKind] | None = None,
    ) -> str:
        budget = budget_tokens if budget_tokens is not None else self.config.default_budget
        ranked = await rank_symbols(
            self.store,
            self._kinds(kinds),
            self.config.damping,
            self.config.edge_weights,
            focus,
            scope,
        )
        return render_map(ranked, budget)
