"""The openCypher compiler — Kuzu and Neo4j (feat-015).

Both backends persist the *open* graph schema through the same ``_rowmap``
shape: a single ``CkgNode`` table/label and a single ``CkgEdge`` type, with the
graph's ``kind`` as a string column (ADR-0005). So a caller's ``(f:Function)``
does not map to a native label — it maps to ``(f:CkgNode {kind: 'Function'})`` —
and a logical property maps to its physical column (``f.path`` -> ``f.sym_path``)
via the curated ``schema.NODE_PROPERTIES`` catalogue. Because that shape is
identical on Kuzu and Neo4j, one compiler body serves both; the two subclasses
exist for the handful of genuine dialect deltas and are near-empty today.

A bare node variable projects/aggregates over the node's ``id`` (a useful scalar
symbol id), so ``RETURN f`` returns ids and ``count(c)`` counts matched nodes.
"""

from __future__ import annotations

from typing import ClassVar

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
from .capability import QuerySettings
from .compile_base import CompiledQuery, Compiler, ParamAllocator
from .schema import PROPERTY_BY_NAME

_NODE_LABEL = "CkgNode"
_EDGE_LABEL = "CkgEdge"
_STRING_OPS = {"STARTS_WITH": "STARTS WITH", "ENDS_WITH": "ENDS WITH", "CONTAINS": "CONTAINS"}


class _Ctx:
    """Per-compile mutable state: the parameter allocator and the set of node
    variables already declared (so a repeated variable is referenced, not
    re-labelled)."""

    def __init__(self) -> None:
        self.params = ParamAllocator()
        self.declared: set[str] = set()


class CypherCompiler(Compiler):
    """AST -> openCypher over the single-table CkgNode/CkgEdge schema."""

    dialect: ClassVar[str] = "cypher"

    def compile(self, ast: QueryAst, settings: QuerySettings) -> CompiledQuery:
        ctx = _Ctx()
        match_txt = ", ".join(self._pattern(p, ctx) for p in ast.match)
        where_txt = f" WHERE {self._expr(ast.where, ctx)}" if ast.where is not None else ""
        ret_txt, columns = self._returns(ast, ctx)
        distinct = "DISTINCT " if ast.distinct else ""
        order_txt = self._order(ast, ctx)
        skip_txt = f" SKIP {ast.skip}" if ast.skip is not None else ""
        limit_txt = f" LIMIT {self.effective_limit(ast, settings) + 1}"
        text = (
            f"MATCH {match_txt}{where_txt} "
            f"RETURN {distinct}{ret_txt}{order_txt}{skip_txt}{limit_txt}"
        )
        return CompiledQuery(text=text, params=dict(ctx.params.params), columns=tuple(columns))

    # --- patterns -----------------------------------------------------------

    def _pattern(self, path: PathPattern, ctx: _Ctx) -> str:
        out = []
        for el in path.elements:
            out.append(self._node(el, ctx) if isinstance(el, NodePattern) else self._rel(el, ctx))
        return "".join(out)

    def _node(self, n: NodePattern, ctx: _Ctx) -> str:
        # A repeated variable is referenced only — declare its label/props once.
        if n.var is not None and n.var in ctx.declared:
            return f"({n.var})"
        if n.var is not None:
            ctx.declared.add(n.var)
        inline: dict[str, object] = {}
        if n.label is not None:
            inline["kind"] = n.label
        for key, lit in n.props:
            inline[PROPERTY_BY_NAME[key].column] = lit.value
        return f"({n.var or ''}:{_NODE_LABEL}{self._inline(inline, ctx)})"

    def _rel(self, r: RelPattern, ctx: _Ctx) -> str:
        left = "<-" if r.direction == "in" else "-"
        right = "->" if r.direction == "out" else "-"
        span = "" if (r.min_hops, r.max_hops) == (1, 1) else f"*{r.min_hops}..{r.max_hops}"
        inline: dict[str, object] = {"kind": r.kind} if r.kind is not None else {}
        return f"{left}[{r.var or ''}:{_EDGE_LABEL}{span}{self._inline(inline, ctx)}]{right}"

    def _inline(self, props: dict[str, object], ctx: _Ctx) -> str:
        if not props:
            return ""
        body = ", ".join(f"{col}: ${ctx.params.add(v)}" for col, v in props.items())
        return f" {{{body}}}"

    # --- WHERE --------------------------------------------------------------

    def _expr(self, expr: Expr, ctx: _Ctx) -> str:
        # One arm per Expr node — adding a construct adds an arm, never edits one.
        match expr:
            case Compare(lhs, op, rhs):
                return f"{self._prop(lhs)} {op} ${ctx.params.add(rhs.value)}"
            case InList(lhs, values):
                items = ", ".join(f"${ctx.params.add(v.value)}" for v in values)
                return f"{self._prop(lhs)} IN [{items}]"
            case StringPred(lhs, op, rhs):
                return f"{self._prop(lhs)} {_STRING_OPS[op]} ${ctx.params.add(rhs)}"
            case Not(operand):
                return f"NOT ({self._expr(operand, ctx)})"
            case BoolOp(op, operands):
                joined = f" {op} ".join(self._expr(o, ctx) for o in operands)
                return f"({joined})"
            case PatternExists(pattern):
                return self._pattern(pattern, ctx)
        raise AssertionError(f"unhandled expr node: {type(expr).__name__}")  # pragma: no cover

    # --- RETURN / ORDER BY --------------------------------------------------

    def _returns(self, ast: QueryAst, ctx: _Ctx) -> tuple[str, list[str]]:
        items: list[str] = []
        columns: list[str] = []
        for item in ast.returns:
            text, default_col = self._return_expr(item.expr)
            columns.append(item.alias or default_col)
            items.append(f"{text} AS {item.alias}" if item.alias is not None else text)
        return ", ".join(items), columns

    def _return_expr(self, expr: ReturnExpr) -> tuple[str, str]:
        match expr:
            case PropRef():
                return self._prop(expr), f"{expr.var}.{'.'.join(expr.path)}"
            case VarRef(var):
                return f"{var}.id", var
            case Aggregate(func, arg, distinct):
                inner = self._agg_arg(arg)
                distinct_txt = "DISTINCT " if distinct else ""
                col = f"{func}({'*' if arg is None else self._agg_label(arg)})"
                return f"{func}({distinct_txt}{inner})", col
        raise AssertionError(f"unhandled return expr: {type(expr).__name__}")  # pragma: no cover

    def _agg_arg(self, arg: PropRef | VarRef | None) -> str:
        if arg is None:
            return "*"
        return f"{arg.var}.id" if isinstance(arg, VarRef) else self._prop(arg)

    def _agg_label(self, arg: PropRef | VarRef) -> str:
        return arg.var if isinstance(arg, VarRef) else f"{arg.var}.{'.'.join(arg.path)}"

    def _order(self, ast: QueryAst, ctx: _Ctx) -> str:
        if not ast.order_by:
            return ""
        aliases = {item.alias for item in ast.returns if item.alias}
        keys: list[str] = []
        for key in ast.order_by:
            if isinstance(key.ref, PropRef):
                ref = self._prop(key.ref)
            elif key.ref.var in aliases:
                ref = key.ref.var  # a RETURN alias
            else:
                ref = f"{key.ref.var}.id"  # a bound node variable
            keys.append(f"{ref} DESC" if key.descending else ref)
        return " ORDER BY " + ", ".join(keys)

    # --- shared -------------------------------------------------------------

    def _prop(self, ref: PropRef) -> str:
        # attrs.* never reaches a Cypher backend (gated by the attrs.access
        # capability, which Kuzu/Neo4j do not advertise), so the path is a
        # single curated segment here.
        return f"{ref.var}.{PROPERTY_BY_NAME[ref.path[0]].column}"


class KuzuCypherCompiler(CypherCompiler):
    """Kuzu deltas over the shared Cypher body (none needed today)."""

    dialect: ClassVar[str] = "kuzu"


class Neo4jCypherCompiler(CypherCompiler):
    """Neo4j deltas over the shared Cypher body (populated in chunk 3)."""

    dialect: ClassVar[str] = "neo4j"
