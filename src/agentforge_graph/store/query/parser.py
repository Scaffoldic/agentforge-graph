"""The Cypher-subset parser: text -> ``QueryAst`` (feat-015).

Hand-written tokenizer + recursive-descent parser over the bounded grammar in
``GRAMMAR.md`` (no parser-library dependency — the base install stays lean). The
parser proves *syntax only*: it produces an AST with raw string labels/kinds and
never executes anything. Vocabulary and safety checks live in ``validator.py``.

Write verbs (CREATE/MERGE/SET/DELETE/…), procedure ``CALL``, ``WITH``/``UNWIND``
and friends have no production here, so they surface as a plain ``ParseError``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agentforge_graph.core import Direction

from .ast import (
    Aggregate,
    BoolOp,
    Compare,
    Expr,
    InList,
    Lit,
    NodePattern,
    Not,
    OrderKey,
    PathPattern,
    PatternExists,
    PropRef,
    QueryAst,
    RelPattern,
    ReturnExpr,
    ReturnItem,
    StringPred,
    VarRef,
)
from .errors import ParseError

# --- tokenizer --------------------------------------------------------------

_KEYWORDS = frozenset(
    {
        "MATCH",
        "WHERE",
        "RETURN",
        "DISTINCT",
        "AS",
        "ORDER",
        "BY",
        "SKIP",
        "LIMIT",
        "AND",
        "OR",
        "NOT",
        "IN",
        "STARTS",
        "ENDS",
        "WITH",
        "CONTAINS",
        "ASC",
        "DESC",
        "TRUE",
        "FALSE",
        "NULL",
    }
)
_AGG_FUNCS = frozenset({"count", "collect", "min", "max", "avg"})

_TOKEN_RE = re.compile(
    r"""
      (?P<WS>\s+)
    | (?P<STRING>'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")
    | (?P<FLOAT>\d+\.\d+)
    | (?P<INT>\d+)
    | (?P<ARROW_R>->)
    | (?P<ARROW_L><-)
    | (?P<LE><=)
    | (?P<GE>>=)
    | (?P<NE><>)
    | (?P<PUNCT>[()\[\]{}:.,*=<>\-])
    | (?P<IDENT>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)


@dataclass(frozen=True)
class _Token:
    type: str
    value: str
    pos: int


def _tokenize(text: str) -> list[_Token]:
    toks: list[_Token] = []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if m is None:
            raise ParseError(f"unexpected character {text[pos]!r}", position=pos, query=text)
        pos = m.end()
        kind = m.lastgroup
        assert kind is not None
        value = m.group()
        if kind == "WS":
            continue
        if kind == "IDENT" and value.upper() in _KEYWORDS:
            toks.append(_Token(value.upper(), value, m.start()))
        elif kind == "PUNCT":
            toks.append(_Token(value, value, m.start()))  # type == the char
        else:
            toks.append(_Token(kind, value, m.start()))
    toks.append(_Token("EOF", "", n))
    return toks


_ESCAPES = {"n": "\n", "t": "\t", "r": "\r"}


def _unquote(raw: str) -> str:
    return re.sub(r"\\(.)", lambda mo: _ESCAPES.get(mo.group(1), mo.group(1)), raw[1:-1])


# --- parser -----------------------------------------------------------------


class _Parser:
    def __init__(self, text: str, tokens: list[_Token]) -> None:
        self.text = text
        self.toks = tokens
        self.i = 0

    # cursor helpers
    def _cur(self) -> _Token:
        return self.toks[self.i]

    def _at(self, type_: str) -> bool:
        return self.toks[self.i].type == type_

    def _next_is(self, type_: str) -> bool:
        return self.toks[self.i + 1].type == type_

    def _advance(self) -> _Token:
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def _accept(self, type_: str) -> _Token | None:
        return self._advance() if self._at(type_) else None

    def _expect(self, type_: str, what: str) -> _Token:
        tok = self.toks[self.i]
        if tok.type != type_:
            found = "end of input" if tok.type == "EOF" else repr(tok.value)
            raise ParseError(f"expected {what}, found {found}", position=tok.pos, query=self.text)
        return self._advance()

    def _name(self, what: str) -> str:
        # A label / relationship type may be a reserved word (e.g. the CONTAINS
        # edge kind clashes with the CONTAINS string operator), so accept an
        # identifier *or* any keyword token in name position.
        tok = self.toks[self.i]
        if tok.type == "IDENT" or tok.type in _KEYWORDS:
            return self._advance().value
        found = "end of input" if tok.type == "EOF" else repr(tok.value)
        raise ParseError(f"expected {what}, found {found}", position=tok.pos, query=self.text)

    # query := MATCH pattern (, pattern)* [WHERE expr] RETURN [DISTINCT] item (, item)*
    #          [ORDER BY key (, key)*] [SKIP int] [LIMIT int]
    def parse(self) -> QueryAst:
        self._expect("MATCH", "'MATCH'")
        patterns = [self._pattern()]
        while self._accept(","):
            patterns.append(self._pattern())

        where: Expr | None = None
        if self._accept("WHERE"):
            where = self._expr()

        self._expect("RETURN", "'RETURN'")
        distinct = self._accept("DISTINCT") is not None
        returns = [self._return_item()]
        while self._accept(","):
            returns.append(self._return_item())

        order_by: list[OrderKey] = []
        if self._accept("ORDER"):
            self._expect("BY", "'BY'")
            order_by.append(self._order_key())
            while self._accept(","):
                order_by.append(self._order_key())

        skip = int(self._expect("INT", "an integer").value) if self._accept("SKIP") else None
        limit = int(self._expect("INT", "an integer").value) if self._accept("LIMIT") else None

        self._expect("EOF", "end of query")
        return QueryAst(
            match=tuple(patterns),
            returns=tuple(returns),
            where=where,
            distinct=distinct,
            order_by=tuple(order_by),
            skip=skip,
            limit=limit,
        )

    # pattern := nodePat (relPat nodePat)*
    def _pattern(self) -> PathPattern:
        elements: list[NodePattern | RelPattern] = [self._node_pattern()]
        while self._at("-") or self._at("ARROW_L"):
            rel = self._rel_pattern()
            node = self._node_pattern()
            elements.append(rel)
            elements.append(node)
        return PathPattern(tuple(elements))

    # nodePat := "(" [var] [":" Label] [ "{" propEq (, propEq)* "}" ] ")"
    def _node_pattern(self) -> NodePattern:
        self._expect("(", "'('")
        var = self._accept("IDENT")
        label = None
        if self._accept(":"):
            label = self._name("a node label")
        props: list[tuple[str, Lit]] = []
        if self._accept("{"):
            props.append(self._prop_eq())
            while self._accept(","):
                props.append(self._prop_eq())
            self._expect("}", "'}'")
        self._expect(")", "')'")
        return NodePattern(var.value if var else None, label, tuple(props))

    def _prop_eq(self) -> tuple[str, Lit]:
        key = self._expect("IDENT", "a property name").value
        self._expect(":", "':'")
        return (key, self._literal())

    # relPat := ("<-"|"-") [ "[" [var] [":" KIND] [varlen] "]" ] ("->"|"-")
    def _rel_pattern(self) -> RelPattern:
        left = self._accept("ARROW_L") is not None
        if not left:
            self._expect("-", "'-' or '<-'")

        var: str | None = None
        kind: str | None = None
        min_hops: int = 1
        max_hops: int | None = 1
        if self._accept("["):
            v = self._accept("IDENT")
            var = v.value if v else None
            if self._accept(":"):
                kind = self._name("a relationship type")
            if self._accept("*"):
                min_hops, max_hops = self._varlen()
            self._expect("]", "']'")

        right = self._accept("ARROW_R") is not None
        if not right:
            self._expect("-", "'-' or '->'")

        if left and right:
            raise ParseError(
                "a relationship cannot point both ways ('<-...->')",
                position=self._cur().pos,
                query=self.text,
            )
        direction: Direction = "in" if left else ("out" if right else "both")
        return RelPattern(var, kind, direction, min_hops, max_hops)

    # varlen (after the "*"): "" | INT | ".." INT? | INT ".." INT?
    def _varlen(self) -> tuple[int, int | None]:
        lo = int(self._advance().value) if self._at("INT") else None
        if self._accept("."):  # a ".." range (two DOT tokens)
            self._expect(".", "'..'")
            hi = int(self._advance().value) if self._at("INT") else None
            return (lo if lo is not None else 1, hi)
        # no range: bare "*" (unbounded) or "*n" (exactly n)
        if lo is None:
            return (1, None)
        return (lo, lo)

    # --- WHERE expression ---------------------------------------------------

    def _expr(self) -> Expr:
        return self._or()

    def _or(self) -> Expr:
        operands = [self._and()]
        while self._accept("OR"):
            operands.append(self._and())
        return operands[0] if len(operands) == 1 else BoolOp("OR", tuple(operands))

    def _and(self) -> Expr:
        operands = [self._not()]
        while self._accept("AND"):
            operands.append(self._not())
        return operands[0] if len(operands) == 1 else BoolOp("AND", tuple(operands))

    def _not(self) -> Expr:
        if self._accept("NOT"):
            return Not(self._not())
        return self._primary()

    def _primary(self) -> Expr:
        if self._at("("):
            # "(" is ambiguous: a grouped expr "(a.x = 1)" vs a pattern-existence
            # predicate "(a)-[:X]->(b)". Try the pattern; a real path (>= 3
            # elements: node rel node) is PatternExists, otherwise backtrack.
            save = self.i
            try:
                pat = self._pattern()
                if len(pat.elements) >= 3:
                    return PatternExists(pat)
            except ParseError:
                pass
            self.i = save
            self._expect("(", "'('")
            inner = self._expr()
            self._expect(")", "')'")
            return inner
        return self._predicate()

    def _predicate(self) -> Expr:
        lhs = self._prop_ref()
        if self._accept("IN"):
            self._expect("[", "'['")
            values = [self._literal()]
            while self._accept(","):
                values.append(self._literal())
            self._expect("]", "']'")
            return InList(lhs, tuple(values))
        if self._accept("STARTS"):
            self._expect("WITH", "'WITH'")
            return StringPred(
                lhs, "STARTS_WITH", _unquote(self._expect("STRING", "a string").value)
            )
        if self._accept("ENDS"):
            self._expect("WITH", "'WITH'")
            return StringPred(lhs, "ENDS_WITH", _unquote(self._expect("STRING", "a string").value))
        if self._accept("CONTAINS"):
            return StringPred(lhs, "CONTAINS", _unquote(self._expect("STRING", "a string").value))
        return Compare(lhs, self._compare_op(), self._literal())

    def _compare_op(self) -> str:
        for type_, op in (
            ("=", "="),
            ("NE", "<>"),
            ("LE", "<="),
            ("GE", ">="),
            ("<", "<"),
            (">", ">"),
        ):
            if self._accept(type_):
                return op
        tok = self._cur()
        raise ParseError(
            f"expected a comparison operator, found {tok.value!r}",
            position=tok.pos,
            query=self.text,
        )

    def _prop_ref(self) -> PropRef:
        var = self._expect("IDENT", "a variable").value
        self._expect(".", "'.' (property access)")
        segs = [self._expect("IDENT", "a property name").value]
        while self._accept("."):
            segs.append(self._expect("IDENT", "a property name").value)
        return PropRef(var, tuple(segs))

    # --- RETURN / ORDER BY --------------------------------------------------

    def _return_item(self) -> ReturnItem:
        expr = self._return_expr()
        alias = self._expect("IDENT", "an alias").value if self._accept("AS") else None
        return ReturnItem(expr, alias)

    def _return_expr(self) -> ReturnExpr:
        if self._at("IDENT") and self._cur().value.lower() in _AGG_FUNCS and self._next_is("("):
            return self._aggregate()
        return self._prop_or_var()

    def _aggregate(self) -> Aggregate:
        func = self._advance().value.lower()
        self._expect("(", "'('")
        distinct = self._accept("DISTINCT") is not None
        arg: PropRef | VarRef | None
        if self._accept("*"):
            if func != "count":
                tok = self._cur()
                raise ParseError(
                    f"only count(*) is allowed, not {func}(*)", position=tok.pos, query=self.text
                )
            arg = None
        else:
            arg = self._prop_or_var()
        self._expect(")", "')'")
        return Aggregate(func, arg, distinct)

    def _prop_or_var(self) -> PropRef | VarRef:
        var = self._expect("IDENT", "a variable").value
        if self._accept("."):
            segs = [self._expect("IDENT", "a property name").value]
            while self._accept("."):
                segs.append(self._expect("IDENT", "a property name").value)
            return PropRef(var, tuple(segs))
        return VarRef(var)

    def _order_key(self) -> OrderKey:
        ref = self._prop_or_var()
        descending = False
        if self._accept("ASC"):
            descending = False
        elif self._accept("DESC"):
            descending = True
        return OrderKey(ref, descending)

    # --- literals -----------------------------------------------------------

    def _literal(self) -> Lit:
        negative = self._accept("-") is not None
        if self._at("INT"):
            v = int(self._advance().value)
            return Lit(-v if negative else v)
        if self._at("FLOAT"):
            f = float(self._advance().value)
            return Lit(-f if negative else f)
        if negative:
            tok = self._cur()
            raise ParseError(
                f"expected a number after '-', found {tok.value!r}",
                position=tok.pos,
                query=self.text,
            )
        if self._at("STRING"):
            return Lit(_unquote(self._advance().value))
        if self._accept("TRUE"):
            return Lit(True)
        if self._accept("FALSE"):
            return Lit(False)
        if self._accept("NULL"):
            return Lit(None)
        tok = self._cur()
        raise ParseError(
            f"expected a literal, found {tok.value!r}", position=tok.pos, query=self.text
        )


def parse_query(text: str) -> QueryAst:
    """Parse Cypher-subset text into a ``QueryAst`` (syntax only).

    Raises ``ParseError`` with the offending offset on malformed input. The
    result is *not yet validated* — call ``validate_query`` next."""
    if not text.strip():
        raise ParseError("empty query")
    return _Parser(text, _tokenize(text)).parse()
