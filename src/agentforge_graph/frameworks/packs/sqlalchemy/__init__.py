"""SQLAlchemy framework pack (feat-011) — declarative ORM models.

Extracts declarative model classes into ``DataModel`` nodes + ``HAS_FIELD``
edges to each mapped column (a ``Variable`` field node carrying its column
type). A class is treated as a model only when its body carries the static
evidence SQLAlchemy declarative mapping requires — a ``__tablename__`` string
or at least one ``Column(...)`` / ``mapped_column(...)`` field — so plain
classes in a SQLAlchemy app never mint false models (ADR-0004).

Both the classic (``name = Column(Integer)``) and 2.0-style
(``name: Mapped[int] = mapped_column()``) field forms are recognised. Intra-
file: model, fields, and `HAS_FIELD` edges all live in the file's
``FileSubgraph`` and ride feat-004 incrementality. ``relationship("X")`` /
``ForeignKey("t.c")`` string targets are recorded on the model node in pass-1
and stitched into cross-file ``RELATES_TO`` edges in pass-2 (``resolve``) — a
unique-match-only resolution against the whole-repo model set (ADR-0004).
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
    GraphStore,
    NodeKind,
    Provenance,
    SourceFile,
    SymbolID,
)
from agentforge_graph.core import Node as GraphNode
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack

_HERE = Path(__file__).parent
_ALL = 10_000_000  # effectively unbounded query for v0.1 graph sizes
_COLUMN_CALLS = {"Column", "mapped_column"}


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


def _first_string_arg(call: TSNode, src: bytes) -> str:
    """The first string-literal positional arg, stripped — the target name in
    ``relationship("Post")`` / ``ForeignKey("users.id")``; "" when non-literal."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return ""
    for arg in args.named_children:
        if arg.type == "string":
            return _strip_quotes(_text(arg, src))
    return ""


def _foreign_key_target(call: TSNode, src: bytes) -> str:
    """A ``ForeignKey("table.col")`` target nested in a ``Column(...)`` arg list
    (``author_id = Column(Integer, ForeignKey("users.id"))``), or ""."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return ""
    for arg in args.named_children:
        if arg.type == "call" and _callee_name(arg, src) == "ForeignKey":
            return _first_string_arg(arg, src)
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
        # pending RELATES_TO targets resolved cross-file in pass-2 (resolve()):
        # relationship("Post") -> class name; ForeignKey("users.id") -> table.col
        relations: list[dict[str, str]] = []
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
                fk = _foreign_key_target(right, src)  # Column(.., ForeignKey("t.c"))
                if fk:
                    relations.append({"field": field_name, "target": fk, "kind": "fk"})
            elif callee == "relationship":
                target = _first_string_arg(right, src)
                if target:
                    relations.append(
                        {"field": field_name, "target": target, "kind": "relationship"}
                    )

        # Conservative: a class is a model only with declarative evidence.
        if table is None and not fields:
            return

        model_id = SymbolID.for_symbol(self.language_slug, repo, file.path, f"model({class_name}).")
        class_id = SymbolID.for_symbol(
            self.language_slug, repo, file.path, Descriptor.type(class_name)
        )
        attrs: dict[str, object] = {
            "framework": self.name,
            "class": class_id,
            "model_class": class_name,  # cross-file RELATES_TO target lookup (pass-2)
        }
        if table is not None:
            attrs["table"] = table
        if relations:
            attrs["relations"] = relations
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

    async def resolve(self, store: GraphStore, commit: str = "") -> list[Edge]:
        """Pass-2: stitch the ``relationship``/``ForeignKey`` string targets
        recorded in pass-1 into ``RELATES_TO`` edges. Targets resolve against the
        whole-repo model set: a ``relationship("Post")`` to the model whose class
        is ``Post``; a ``ForeignKey("users.id")`` to the model whose table is
        ``users``. Ambiguous class names (same name in two files) are left
        unresolved (ADR-0004 — never guess)."""
        from agentforge_graph.core import GraphQuery

        models = (await store.query(GraphQuery(kinds=[NodeKind.DATA_MODEL], limit=_ALL))).nodes
        models = [m for m in models if m.attrs.get("framework") == self.name]

        by_class: dict[str, set[str]] = {}
        by_table: dict[str, set[str]] = {}
        for m in models:
            cls = str(m.attrs.get("model_class", ""))
            if cls:
                by_class.setdefault(cls, set()).add(m.id)
            tbl = str(m.attrs.get("table", ""))
            if tbl:
                by_table.setdefault(tbl, set()).add(m.id)

        prov = Provenance.resolved(f"pack:{self.name}@{self.version}", commit)
        edges: list[Edge] = []
        seen: set[tuple[str, str]] = set()
        for m in models:
            relations = m.attrs.get("relations") or []
            for rel in relations:
                target_id = _resolve_target(rel, by_class, by_table)
                if target_id is None:
                    continue
                key = (m.id, target_id)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    Edge(
                        src=m.id,
                        dst=target_id,
                        kind=EdgeKind.RELATES_TO,
                        attrs={"kind": str(rel.get("kind", "")), "via": str(rel.get("field", ""))},
                        provenance=prov,
                        origin_path=SymbolID.parse(m.id).path,
                    )
                )
        return edges


def _resolve_target(
    rel: dict[str, str], by_class: dict[str, set[str]], by_table: dict[str, set[str]]
) -> str | None:
    """Resolve one pending relation to a target model id, or None when the
    target is external/ambiguous (unique match only — ADR-0004)."""
    target = str(rel.get("target", ""))
    if not target:
        return None
    if rel.get("kind") == "fk":
        # "users.id" / "schema.users.id" -> the table segment (second-to-last)
        parts = target.split(".")
        table = parts[-2] if len(parts) >= 2 else parts[0]
        candidates = by_table.get(table)
    else:  # relationship("Post") / "module.Post" -> bare class name
        name = target.rsplit(".", 1)[-1]
        candidates = by_class.get(name)
    if candidates is None or len(candidates) != 1:
        return None
    return next(iter(candidates))


SQLALCHEMY_PACK = SQLAlchemyPack()
