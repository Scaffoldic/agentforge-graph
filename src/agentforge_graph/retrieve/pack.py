"""The retrieval result: a ranked, deduped, connected context pack.

``render`` packs highest-score items first, emits whole code blocks (never
splits a chunk), and degrades an over-budget item to its signature line.
``to_dict`` is the structured form feat-008 tools return.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agentforge_graph.chunking import estimate_tokens
from agentforge_graph.core import NodeKind, Source


class ContextItem(BaseModel):
    id: str  # symbol or chunk id
    kind: NodeKind
    name: str
    score: float
    path: str
    span: tuple[int, int] | None = None
    code: str | None = None  # chunk text, rendered verbatim
    provenance: Source
    why: list[str] = Field(default_factory=list)  # trace of how it was included

    def signature(self) -> str:
        loc = f":{self.span[0]}-{self.span[1]}" if self.span else ""
        return f"{self.path}{loc}  {self.name} ({self.kind.value})  score={self.score:.2f}"

    def block(self) -> str:
        if self.code:
            return f"# {self.signature()}\n{self.code}"
        return self.signature()


class ContextPack(BaseModel):
    query: str | None = None
    symbol: str | None = None
    mode: str = "context"
    items: list[ContextItem] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def render(self, budget_tokens: int) -> str:
        out: list[str] = []
        used = 0
        dropped = 0
        for item in self.items:  # already score-sorted
            block = item.block()
            cost = estimate_tokens(block)
            if used + cost <= budget_tokens:
                out.append(block)
                used += cost
                continue
            sig = item.signature()  # degrade to a signature instead of splitting
            sig_cost = estimate_tokens(sig)
            if used + sig_cost <= budget_tokens:
                out.append(sig)
                used += sig_cost
            else:
                dropped += 1
        footer: list[str] = []
        if dropped:
            footer.append(f"… {dropped} more item(s) omitted (token budget)")
        footer.extend(self.notes)
        if footer:
            out.append("\n".join(footer))
        return "\n\n".join(out)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()
