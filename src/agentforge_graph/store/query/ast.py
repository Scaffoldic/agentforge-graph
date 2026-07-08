"""The read-only query AST — the single trust boundary (feat-015).

Caller text is parsed into these frozen dataclasses and nothing else runs.
Anything the AST cannot represent cannot reach a backend: there is no node for
a write, a procedure call, or an unbounded path, so those are unexpressible by
construction (the parser has no production for them, and the validator rejects
the few dangerous shapes the grammar *can* express, e.g. an unbounded
variable-length rel).

Labels/kinds/property keys are kept as **raw strings** here — the parser only
proves *syntax*. The validator (``validator.py``) is what checks them against
the locked feat-001 vocabulary, so parse (syntax) and validate (meaning) stay
cleanly separated.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentforge_graph.core import Direction

# A scalar literal value the caller wrote (string/int/float/bool/null).
type LitValue = str | int | float | bool | None


@dataclass(frozen=True)
class Lit:
    """A literal value, wrapped so ``None`` is unambiguous vs "absent"."""

    value: LitValue


@dataclass(frozen=True)
class PropRef:
    """A property access: ``f.name``, ``f.path``, ``n.attrs.role``."""

    var: str
    path: tuple[str, ...]  # ("name",) | ("attrs", "role")


@dataclass(frozen=True)
class VarRef:
    """A bare bound variable, e.g. ``RETURN f`` or ``count(f)``."""

    var: str


# --- MATCH patterns ---------------------------------------------------------


@dataclass(frozen=True)
class NodePattern:
    var: str | None
    label: str | None  # raw; validated against NodeKind later
    props: tuple[tuple[str, Lit], ...] = ()  # inline {key: literal} equalities


@dataclass(frozen=True)
class RelPattern:
    var: str | None
    kind: str | None  # raw; validated against EdgeKind later
    direction: Direction  # "out" (->) | "in" (<-) | "both" (-)
    min_hops: int = 1
    max_hops: int | None = 1  # None => unbounded [*] => rejected by the validator


@dataclass(frozen=True)
class PathPattern:
    """Alternating ``NodePattern (RelPattern NodePattern)*``."""

    elements: tuple[NodePattern | RelPattern, ...]


# --- WHERE expression tree (a closed set) -----------------------------------


@dataclass(frozen=True)
class Compare:
    lhs: PropRef
    op: str  # = | <> | < | <= | > | >=
    rhs: Lit


@dataclass(frozen=True)
class InList:
    lhs: PropRef
    values: tuple[Lit, ...]


@dataclass(frozen=True)
class StringPred:
    lhs: PropRef
    op: str  # STARTS_WITH | ENDS_WITH | CONTAINS
    rhs: str


@dataclass(frozen=True)
class Not:
    operand: Expr


@dataclass(frozen=True)
class BoolOp:
    op: str  # AND | OR
    operands: tuple[Expr, ...]


@dataclass(frozen=True)
class PatternExists:
    """Existence of a path in a WHERE clause, e.g. ``NOT (f)<-[:CALLS]-()``."""

    pattern: PathPattern


type Expr = Compare | InList | StringPred | Not | BoolOp | PatternExists


# --- RETURN / ORDER BY ------------------------------------------------------


@dataclass(frozen=True)
class Aggregate:
    func: str  # count | collect | min | max | avg
    arg: PropRef | VarRef | None  # None == count(*)
    distinct: bool = False


type ReturnExpr = PropRef | VarRef | Aggregate


@dataclass(frozen=True)
class ReturnItem:
    expr: ReturnExpr
    alias: str | None = None


@dataclass(frozen=True)
class OrderKey:
    ref: PropRef | VarRef  # a property or a bound var / RETURN alias
    descending: bool = False


@dataclass(frozen=True)
class QueryAst:
    """A fully-parsed read-only query."""

    match: tuple[PathPattern, ...]
    returns: tuple[ReturnItem, ...]
    where: Expr | None = None
    distinct: bool = False
    order_by: tuple[OrderKey, ...] = ()
    skip: int | None = None
    limit: int | None = None
