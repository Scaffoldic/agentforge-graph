"""A portable query interpreter over the ``GraphStore`` ABC (feat-015).

Kuzu and Neo4j speak openCypher, so they *compile* the AST to native Cypher.
Other backends do not — SurrealDB, for instance, models edges as a document
table (``src``/``dst`` string fields), with no native graph traversal to compile
to. Rather than a fragile per-dialect translator, those backends *interpret* the
AST: this engine evaluates a validated ``QueryAst`` using only the locked
``GraphStore`` read methods (``query``/``adjacent``/``get``), in Python.

That makes query support **universal** — any ``GraphStore`` is query-capable for
free — and it is inherently **read-only** (there is no write path through the
ABC). Both the compiled and interpreted paths pass the same ``QueryConformance``
suite, so their results are identical to the canonical rows.

Bounds (row cap / expansion cap / timeout) are enforced here just as the compiled
path enforces them in ``execute.py``: intermediate bindings are capped at
``max_expansions``, the wall-clock deadline is checked between steps, and the row
cap trims the final rows (all reported via ``stopped_reason``).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from agentforge_graph.core import EdgeKind, GraphQuery, GraphStore, Node, NodeKind, SymbolID

from .ast import (
    Aggregate,
    BoolOp,
    Compare,
    Expr,
    InList,
    NodePattern,
    Not,
    PathPattern,
    PatternExists,
    PropRef,
    QueryAst,
    RelPattern,
    ReturnExpr,
    StringPred,
    VarRef,
)
from .capability import QuerySettings, ResultTable

Binding = dict[str, Node]
Row = tuple[Any, ...]

_COMPARATORS: dict[str, Callable[[Any, Any], bool]] = {
    "=": lambda a, b: a == b,
    "<>": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}


def node_property(node: Node, path: tuple[str, ...]) -> Any:
    """Resolve a logical property path against a ``Node`` — the interpreter twin
    of the compiler's logical-name -> physical-column map."""
    if path[0] == "attrs":
        value: Any = node.attrs
        for seg in path[1:]:
            if not isinstance(value, dict):
                return None
            value = value.get(seg)
        return value
    name = path[0]
    p = node.provenance
    return {
        "name": node.name,
        "kind": node.kind.value,
        "path": SymbolID.parse(node.id).path,
        "start_line": node.span[0] if node.span else None,
        "end_line": node.span[1] if node.span else None,
        "source": p.source.value,
        "extractor": p.extractor,
        "commit": p.commit,
        "confidence": p.confidence,
    }.get(name)


class InterpretingQueryEngine:
    """Evaluates a validated ``QueryAst`` against a ``GraphStore`` via the ABC."""

    def __init__(self, store: GraphStore) -> None:
        self._store = store

    async def run(
        self,
        ast: QueryAst,
        settings: QuerySettings,
        now: Callable[[], float] = time.monotonic,
    ) -> ResultTable:
        self._settings = settings
        self._deadline = now() + settings.timeout_ms / 1000
        self._now = now
        self._stopped: str | None = None

        bindings = await self._match_all(ast)
        if ast.where is not None:
            kept = []
            for b in bindings:
                if await self._truth(ast.where, b):
                    kept.append(b)
            bindings = kept
        columns, rows = self._project(ast, bindings)
        if ast.skip:
            rows = rows[ast.skip :]
        limit = self._effective_limit(ast)
        truncated = self._stopped is not None or len(rows) > limit
        reason = self._stopped or ("row_cap" if len(rows) > limit else None)
        return ResultTable(
            columns=tuple(columns),
            rows=tuple(rows[:limit]),
            truncated=truncated,
            stopped_reason=reason,
        )

    def _effective_limit(self, ast: QueryAst) -> int:
        if ast.limit is None:
            return self._settings.max_rows
        return min(ast.limit, self._settings.max_rows)

    def _over_budget(self, count: int) -> bool:
        if self._now() >= self._deadline:
            self._stopped = "timeout"
            return True
        if count > self._settings.max_expansions:
            self._stopped = "expansion_cap"
            return True
        return False

    # --- MATCH --------------------------------------------------------------

    async def _match_all(self, ast: QueryAst) -> list[Binding]:
        bindings: list[Binding] = [{}]
        for pattern in ast.match:
            extended: list[Binding] = []
            for b in bindings:
                for nb in await self._extend_pattern(pattern, b):
                    extended.append(nb)
                    if self._over_budget(len(extended)):
                        return extended[: self._settings.max_expansions]
            bindings = extended
        return bindings

    async def _extend_pattern(self, pattern: PathPattern, base: Binding) -> list[Binding]:
        els = pattern.elements
        # state: (binding, current_node) — carries the node the next rel starts from
        state: list[tuple[Binding, Node]] = list(await self._bind_first(els[0], base))
        idx = 1
        while idx < len(els):
            rel = els[idx]
            nxt = els[idx + 1]
            idx += 2
            assert isinstance(rel, RelPattern) and isinstance(nxt, NodePattern)
            new_state: list[tuple[Binding, Node]] = []
            for b, cur in state:
                for tid in await self._reachable(cur.id, rel):
                    target = await self._store.get(tid)
                    if target is None:
                        continue
                    bound = self._bind_specific(nxt, b, target)
                    if bound is not None:
                        new_state.append((bound, target))
            state = new_state
        return [b for b, _ in state]

    async def _bind_first(
        self, node: NodePattern | RelPattern, base: Binding
    ) -> list[tuple[Binding, Node]]:
        assert isinstance(node, NodePattern)
        if node.var is not None and node.var in base:  # already bound upstream
            fixed = base[node.var]
            return [(base, fixed)] if self._matches(node, fixed) else []
        out: list[tuple[Binding, Node]] = []
        for cand in await self._candidates(node):
            b = dict(base)
            if node.var is not None:
                b[node.var] = cand
            out.append((b, cand))
        return out

    def _bind_specific(self, node: NodePattern, base: Binding, target: Node) -> Binding | None:
        if not self._matches(node, target):
            return None
        if node.var is not None:
            if node.var in base:
                return base if base[node.var].id == target.id else None
            b = dict(base)
            b[node.var] = target
            return b
        return base

    async def _candidates(self, node: NodePattern) -> list[Node]:
        name = next((lit.value for k, lit in node.props if k == "name"), None)
        gq = GraphQuery(
            kinds=[NodeKind(node.label)] if node.label else None,
            name=name if isinstance(name, str) else None,
            limit=self._settings.max_expansions + 1,
        )
        result = await self._store.query(gq)
        return [n for n in result.nodes if self._matches(node, n)]

    def _matches(self, node: NodePattern, n: Node) -> bool:
        if node.label is not None and n.kind.value != node.label:
            return False
        return all(node_property(n, (key,)) == lit.value for key, lit in node.props)

    async def _reachable(self, start_id: str, rel: RelPattern) -> set[str]:
        if (rel.min_hops, rel.max_hops) == (1, 1):
            return set(await self._one_hop(start_id, rel))
        results: set[str] = set()
        frontier = {start_id}
        visited = {start_id}
        for depth in range(1, (rel.max_hops or 1) + 1):
            nxt: set[str] = set()
            for nid in frontier:
                nxt.update(await self._one_hop(nid, rel))
            if depth >= rel.min_hops:
                results |= nxt
            frontier = nxt - visited
            visited |= nxt
            if not frontier:
                break
        return results

    async def _one_hop(self, cur_id: str, rel: RelPattern) -> list[str]:
        kinds = [EdgeKind(rel.kind)] if rel.kind else None
        edges = await self._store.adjacent(cur_id, kinds, rel.direction)
        out: list[str] = []
        for e in edges:
            if rel.direction == "out":
                out.append(e.dst)
            elif rel.direction == "in":
                out.append(e.src)
            else:
                out.append(e.dst if e.src == cur_id else e.src)
        return out

    # --- WHERE --------------------------------------------------------------

    async def _truth(self, expr: Expr, b: Binding) -> bool:
        match expr:
            case Compare(lhs, op, rhs):
                left = node_property(b[lhs.var], lhs.path)
                if left is None:
                    return False
                try:
                    return _COMPARATORS[op](left, rhs.value)
                except TypeError:
                    return False
            case InList(lhs, values):
                return node_property(b[lhs.var], lhs.path) in [v.value for v in values]
            case StringPred(lhs, op, rhs):
                left = node_property(b[lhs.var], lhs.path)
                if left is None:
                    return False
                s = str(left)
                if op == "STARTS_WITH":
                    return s.startswith(rhs)
                if op == "ENDS_WITH":
                    return s.endswith(rhs)
                return rhs in s
            case Not(operand):
                return not await self._truth(operand, b)
            case BoolOp(op, operands):
                if op == "AND":
                    for o in operands:
                        if not await self._truth(o, b):
                            return False
                    return True
                for o in operands:
                    if await self._truth(o, b):
                        return True
                return False
            case PatternExists(pattern):
                return bool(await self._extend_pattern(pattern, b))
        raise AssertionError(f"unhandled expr: {type(expr).__name__}")  # pragma: no cover

    # --- RETURN / ORDER BY --------------------------------------------------

    def _project(self, ast: QueryAst, bindings: list[Binding]) -> tuple[list[str], list[Row]]:
        columns = [item.alias or self._default_col(item.expr) for item in ast.returns]
        if not any(isinstance(it.expr, Aggregate) for it in ast.returns):
            # Order the bindings first, so ORDER BY can reference any property of a
            # bound variable — even one not projected (matching the compiled path).
            bindings = self._order_bindings(ast, bindings)
            rows = [tuple(self._value(it.expr, b) for it in ast.returns) for b in bindings]
            if ast.distinct:
                rows = list(dict.fromkeys(rows))
            return columns, rows
        # grouped aggregation: group by the non-aggregate return values
        non_agg = [it for it in ast.returns if not isinstance(it.expr, Aggregate)]
        groups: dict[Row, list[Binding]] = {}
        for b in bindings:
            key = tuple(self._value(it.expr, b) for it in non_agg)
            groups.setdefault(key, []).append(b)
        rows = []
        for key, members in groups.items():
            row: list[Any] = []
            ki = 0
            for it in ast.returns:
                if isinstance(it.expr, Aggregate):
                    row.append(self._aggregate(it.expr, members))
                else:
                    row.append(key[ki])
                    ki += 1
            rows.append(tuple(row))
        return columns, self._order_rows(ast, columns, rows)

    def _value(self, expr: ReturnExpr, b: Binding) -> Any:
        if isinstance(expr, PropRef):
            return node_property(b[expr.var], expr.path)
        if isinstance(expr, VarRef):
            return b[expr.var].id
        raise AssertionError("aggregate handled in grouping")  # pragma: no cover

    def _default_col(self, expr: ReturnExpr) -> str:
        if isinstance(expr, PropRef):
            return f"{expr.var}.{'.'.join(expr.path)}"
        if isinstance(expr, VarRef):
            return expr.var
        star = "*" if expr.arg is None else self._agg_label(expr.arg)
        return f"{expr.func}({star})"

    def _agg_label(self, arg: PropRef | VarRef) -> str:
        return arg.var if isinstance(arg, VarRef) else f"{arg.var}.{'.'.join(arg.path)}"

    def _aggregate(self, agg: Aggregate, members: list[Binding]) -> Any:
        if agg.arg is None:  # count(*)
            return len(members)
        raw = [self._value(agg.arg, b) for b in members]
        values = [v for v in raw if v is not None]
        if agg.distinct:
            values = list(dict.fromkeys(values))
        if agg.func == "count":
            return len(values)
        if agg.func == "collect":
            return sorted(values, key=_sort_key)
        if not values:
            return None
        if agg.func == "min":
            return min(values, key=_sort_key)
        if agg.func == "max":
            return max(values, key=_sort_key)
        return sum(values) / len(values)  # avg

    def _order_bindings(self, ast: QueryAst, bindings: list[Binding]) -> list[Binding]:
        if not ast.order_by:
            return bindings
        alias_expr = {it.alias: it.expr for it in ast.returns if it.alias}
        ordered = list(bindings)
        for ok in reversed(ast.order_by):  # stable, least-significant first
            ordered.sort(key=self._binding_key(ok.ref, alias_expr), reverse=ok.descending)
        return ordered

    def _binding_key(
        self, ref: PropRef | VarRef, alias_expr: dict[str, Any]
    ) -> Callable[[Binding], tuple[int, Any]]:
        return lambda b: _sort_key(self._order_value(ref, b, alias_expr))

    def _order_value(self, ref: PropRef | VarRef, b: Binding, alias_expr: dict[str, Any]) -> Any:
        if isinstance(ref, PropRef):
            return node_property(b[ref.var], ref.path)
        if ref.var in alias_expr:  # a RETURN alias
            return self._value(alias_expr[ref.var], b)
        return b[ref.var].id  # a bound variable

    def _order_rows(self, ast: QueryAst, columns: list[str], rows: list[Row]) -> list[Row]:
        # Aggregate results are rows, not bindings, so ORDER BY must name a column
        # (a RETURN alias or grouping key), which the validator guarantees.
        if not ast.order_by:
            return rows
        keys: list[tuple[int, bool]] = []
        for ok in ast.order_by:
            col = (
                ok.ref.var
                if isinstance(ok.ref, VarRef)
                else f"{ok.ref.var}.{'.'.join(ok.ref.path)}"
            )
            if col in columns:
                keys.append((columns.index(col), ok.descending))
        ordered = list(rows)
        for idx, descending in reversed(keys):  # stable, least-significant first
            ordered.sort(key=self._row_key(idx), reverse=descending)
        return ordered

    def _row_key(self, idx: int) -> Callable[[Row], tuple[int, Any]]:
        return lambda r: _sort_key(r[idx])


def _sort_key(value: Any) -> tuple[int, Any]:
    """None-safe, type-stable sort key: None first, then by (type-name, value)."""
    if value is None:
        return (0, "")
    return (1, (type(value).__name__, value))
