"""SQLAlchemy framework pack (feat-011) — declarative ORM models.

Extracts declarative model classes into ``DataModel`` nodes + ``HAS_FIELD``
edges to each mapped column (a ``Variable`` field node carrying its column
type). A class is treated as a model only when its body carries the static
evidence SQLAlchemy declarative mapping requires — a ``__tablename__`` string
or at least one ``Column(...)`` / ``mapped_column(...)`` field — so plain
classes in a SQLAlchemy app never mint false models (ADR-0004).

Both the classic (``name = Column(Integer)``) and 2.0-style
(``name: Mapped[int] = mapped_column()``) field forms are recognised. Intra-
file: model, fields, and edges all live in the file's ``FileSubgraph`` and ride
feat-004 incrementality. Relationship/foreign-key edges (``RELATES_TO``) cross
files via string targets and are a pass-2 follow-up; they are counted as
unresolved here, never silently dropped.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tree_sitter import Language, Parser, Query, QueryCursor
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language

from agentforge_graph.core import (
    Descriptor,
    Edge,
    EdgeKind,
    NodeKind,
    Provenance,
    SourceFile,
    SymbolID,
)
from agentforge_graph.core import Node as GraphNode
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack

_HERE = Path(__file__).parent
_COLUMN_CALLS = {"Column", "mapped_column"}
# relationship()/ForeignKey() are the RELATES_TO signal — recognised but
# deferred to the cross-file pass-2 follow-up; counted as unresolved here.
_RELATION_CALLS = {"relationship", "ForeignKey"}


@cache
def _language() -> Language:
    return get_language("python")


@cache
def _query_text() -> str:
    return (_HERE / "models.scm").read_text(encoding="utf-8")


def _text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _strip_quotes(s: str) -> str:
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _callee_name(call: TSNode, src: bytes) -> str:
    """Last segment of a call's function name: ``Column`` for ``Column(...)`` and
    ``sa.Column(...)`` alike."""
    fn = call.child_by_field_name("function")
    if fn is None:
        return ""
    if fn.type == "attribute":
        attr = fn.child_by_field_name("attribute")
        return _text(attr, src) if attr is not None else ""
    return _text(fn, src)


def _positional_type(call: TSNode, src: bytes) -> str:
    """The column's SQL type from the first positional arg: ``Integer`` for
    ``Column(Integer)`` / ``Column(String(50))``. Keyword args are skipped."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return ""
    for arg in args.named_children:
        if arg.type == "keyword_argument":
            continue
        if arg.type == "call":  # String(50) -> String
            return _callee_name(arg, src)
        if arg.type in ("identifier", "attribute"):
            return _callee_name(arg, src) if arg.type == "attribute" else _text(arg, src)
        return ""
    return ""


def _mapped_type(assignment: TSNode, src: bytes) -> str:
    """The inner type of a ``Mapped[X]`` annotation (``int`` for
    ``id: Mapped[int]``), or "" when there is no such annotation."""
    type_node = assignment.child_by_field_name("type")
    if type_node is None:
        return ""
    generic = type_node.named_children[0] if type_node.named_children else None
    if generic is None or generic.type != "generic_type":
        return ""
    base = generic.named_children[0] if generic.named_children else None
    if base is None or _text(base, src) != "Mapped":
        return ""
    # `Mapped[int]` -> generic_type with a `type_parameter` holding `(type (identifier))`
    targs = next((c for c in generic.named_children if c.type == "type_parameter"), None)
    if targs is None or not targs.named_children:
        return ""
    inner = targs.named_children[0]
    leaf = inner.named_children[0] if inner.type == "type" and inner.named_children else inner
    return _text(leaf, src)


def _class_body(class_node: TSNode) -> TSNode | None:
    return class_node.child_by_field_name("body")


class SQLAlchemyPack(FrameworkPack):
    name = "sqlalchemy"
    language = "python"
    language_slug = "py"  # SymbolID slug — must match the Python language pack
    version = "1"
    dep_names = ("sqlalchemy",)
    import_markers = ("import sqlalchemy", "from sqlalchemy")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(_language()).parse(src).root_node
        query = Query(_language(), _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()

        for _pattern, caps in QueryCursor(query).matches(root):
            class_caps = caps.get("model")
            name_caps = caps.get("name")
            if not (class_caps and name_caps):
                continue
            self._extract_model(
                class_caps[0], _text(name_caps[0], src), src, repo, file, prov, facts
            )
        return facts

    def _extract_model(
        self,
        class_node: TSNode,
        class_name: str,
        src: bytes,
        repo: str,
        file: SourceFile,
        prov: Provenance,
        facts: FrameworkFacts,
    ) -> None:
        body = _class_body(class_node)
        if body is None:
            return

        table: str | None = None
        fields: list[tuple[str, str, TSNode]] = []  # (name, column_type, assignment node)
        relations = 0
        for stmt in body.named_children:
            # a class-level field is `name = Column(...)`; the block may hold the
            # assignment directly or wrapped in an expression_statement.
            if stmt.type == "assignment":
                assign = stmt
            elif stmt.type == "expression_statement" and stmt.named_children:
                assign = stmt.named_children[0]
                if assign.type != "assignment":
                    continue
            else:
                continue
            left = assign.child_by_field_name("left")
            right = assign.child_by_field_name("right")
            if left is None or left.type != "identifier" or right is None:
                continue
            field_name = _text(left, src)

            if field_name == "__tablename__" and right.type == "string":
                table = _strip_quotes(_text(right, src))
                continue
            if right.type != "call":
                continue
            callee = _callee_name(right, src)
            if callee in _COLUMN_CALLS:
                col_type = _positional_type(right, src) or _mapped_type(assign, src)
                fields.append((field_name, col_type, assign))
            elif callee in _RELATION_CALLS:
                relations += 1  # RELATES_TO — pass-2 follow-up, counted not dropped

        # Conservative: a class is a model only with declarative evidence.
        if table is None and not fields:
            return

        model_id = SymbolID.for_symbol(self.language_slug, repo, file.path, f"model({class_name}).")
        class_id = SymbolID.for_symbol(
            self.language_slug, repo, file.path, Descriptor.type(class_name)
        )
        attrs: dict[str, object] = {"framework": self.name, "class": class_id}
        if table is not None:
            attrs["table"] = table
        facts.nodes.append(
            GraphNode(
                id=model_id,
                kind=NodeKind.DATA_MODEL,
                name=table or class_name,
                span=(class_node.start_point[0] + 1, class_node.end_point[0] + 1),
                attrs=attrs,
                provenance=prov,
            )
        )
        for field_name, col_type, assign in fields:
            field_id = SymbolID.for_symbol(
                self.language_slug,
                repo,
                file.path,
                Descriptor.type(class_name) + Descriptor.term(field_name),
            )
            facts.nodes.append(
                GraphNode(
                    id=field_id,
                    kind=NodeKind.VARIABLE,
                    name=field_name,
                    span=(assign.start_point[0] + 1, assign.end_point[0] + 1),
                    attrs={"column_type": col_type, "framework": self.name},
                    provenance=prov,
                )
            )
            facts.edges.append(
                Edge(src=model_id, dst=field_id, kind=EdgeKind.HAS_FIELD, provenance=prov)
            )
        facts.unresolved += relations


SQLALCHEMY_PACK = SQLAlchemyPack()
