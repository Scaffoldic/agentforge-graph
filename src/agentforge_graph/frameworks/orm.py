"""Shared ORM pass-2 helpers (feat-011).

The cross-file ``RELATES_TO`` stitch is the same shape for every ORM pack: load
the whole-repo model set, index it by class name and table, then turn each
model's pending ``relations`` (recorded in pass-1) into edges via a unique-match
lookup (ADR-0004 — never guess an ambiguous target). Only the per-relation
target resolution differs per framework, so that is injected as a callback.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)

_ALL = 10_000_000  # effectively unbounded query for v0.1 graph sizes


class ModelIndex:
    """Whole-repo model lookup by class name and table, each mapping to the set
    of model ids carrying it (so duplicates are detectable and never guessed)."""

    def __init__(self, models: Iterable[Node]) -> None:
        self.by_class: dict[str, set[str]] = {}
        self.by_table: dict[str, set[str]] = {}
        for m in models:
            cls = str(m.attrs.get("model_class", ""))
            if cls:
                self.by_class.setdefault(cls, set()).add(m.id)
            tbl = str(m.attrs.get("table", ""))
            if tbl:
                self.by_table.setdefault(tbl, set()).add(m.id)

    def unique_class(self, name: str) -> str | None:
        return _unique(self.by_class.get(name))

    def unique_table(self, name: str) -> str | None:
        return _unique(self.by_table.get(name))


def _unique(ids: set[str] | None) -> str | None:
    return next(iter(ids)) if ids and len(ids) == 1 else None


async def framework_models(store: GraphStore, framework: str) -> list[Node]:
    """Every ``DataModel`` node emitted by ``framework``."""
    nodes = (await store.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=_ALL))).nodes
    return [m for m in nodes if m.attrs.get("framework") == framework]


def relations_to_edges(
    models: list[Node],
    index: ModelIndex,
    resolve_target: Callable[[dict[str, str], ModelIndex], str | None],
    prov: Provenance,
) -> list[Edge]:
    """Build deduped ``RELATES_TO`` edges from each model's pending relations.
    ``resolve_target`` maps one relation dict to a target model id (or None when
    external/ambiguous). Edges carry ``attrs.kind`` (relationship/fk/m2m/…) and
    ``attrs.via`` (the field), owned by the source model's file for incremental
    invalidation."""
    edges: list[Edge] = []
    seen: set[tuple[str, str, str]] = set()
    for m in models:
        for rel in m.attrs.get("relations") or []:
            target_id = resolve_target(rel, index)
            if target_id is None:
                continue
            kind = str(rel.get("kind", ""))
            key = (m.id, target_id, kind)
            if key in seen:
                continue
            seen.add(key)
            edges.append(
                Edge(
                    src=m.id,
                    dst=target_id,
                    kind=EdgeKind.RELATES_TO,
                    attrs={"kind": kind, "via": str(rel.get("field", ""))},
                    provenance=prov,
                    origin_path=SymbolID.parse(m.id).path,
                )
            )
    return edges
