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

from tree_sitter import Node as TSNode
from tree_sitter import Parser, Query, QueryCursor

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
from agentforge_graph.frameworks.orm import (
    ModelIndex,
    framework_models,
    relations_to_edges,
)
from agentforge_graph.frameworks.packs._python_ast import (
    callee_name,
    class_body,
    first_string_arg,
    iter_class_assignments,
    python_language,
    strip_quotes,
    text,
)

_HERE = Path(__file__).parent
_COLUMN_CALLS = {"Column", "mapped_column"}


@cache
def _query_text() -> str:
    return (_HERE / "models.scm").read_text(encoding="utf-8")


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
            return callee_name(arg, src)
        if arg.type in ("identifier", "attribute"):
            return callee_name(arg, src) if arg.type == "attribute" else text(arg, src)
        return ""
    return ""


def _foreign_key_target(call: TSNode, src: bytes) -> str:
    """A ``ForeignKey("table.col")`` target nested in a ``Column(...)`` arg list
    (``author_id = Column(Integer, ForeignKey("users.id"))``), or ""."""
    args = call.child_by_field_name("arguments")
    if args is None:
        return ""
    for arg in args.named_children:
        if arg.type == "call" and callee_name(arg, src) == "ForeignKey":
            return first_string_arg(arg, src)
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
    if base is None or text(base, src) != "Mapped":
        return ""
    # `Mapped[int]` -> generic_type with a `type_parameter` holding `(type (identifier))`
    targs = next((c for c in generic.named_children if c.type == "type_parameter"), None)
    if targs is None or not targs.named_children:
        return ""
    inner = targs.named_children[0]
    leaf = inner.named_children[0] if inner.type == "type" and inner.named_children else inner
    return text(leaf, src)


class SQLAlchemyPack(FrameworkPack):
    name = "sqlalchemy"
    language = "python"
    language_slug = "py"  # SymbolID slug — must match the Python language pack
    version = "1"
    dep_names = ("sqlalchemy",)
    import_markers = ("import sqlalchemy", "from sqlalchemy")

    def extract(self, file: SourceFile, repo: str, commit: str) -> FrameworkFacts:
        src = file.text.encode("utf-8")
        root = Parser(python_language()).parse(src).root_node
        query = Query(python_language(), _query_text())
        prov = Provenance.parsed(f"pack:{self.name}@{self.version}", commit)
        facts = FrameworkFacts()

        for _pattern, caps in QueryCursor(query).matches(root):
            class_caps = caps.get("model")
            name_caps = caps.get("name")
            if not (class_caps and name_caps):
                continue
            self._extract_model(
                class_caps[0], text(name_caps[0], src), src, repo, file, prov, facts
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
        body = class_body(class_node)
        if body is None:
            return

        table: str | None = None
        fields: list[tuple[str, str, TSNode]] = []  # (name, column_type, assignment node)
        # pending RELATES_TO targets resolved cross-file in pass-2 (resolve()):
        # relationship("Post") -> class name; ForeignKey("users.id") -> table.col
        relations: list[dict[str, str]] = []
        for field_name, assign, right in iter_class_assignments(body, src):
            if field_name == "__tablename__" and right.type == "string":
                table = strip_quotes(text(right, src))
                continue
            if right.type != "call":
                continue
            callee = callee_name(right, src)
            if callee in _COLUMN_CALLS:
                col_type = _positional_type(right, src) or _mapped_type(assign, src)
                fields.append((field_name, col_type, assign))
                fk = _foreign_key_target(right, src)  # Column(.., ForeignKey("t.c"))
                if fk:
                    relations.append({"field": field_name, "target": fk, "kind": "fk"})
            elif callee == "relationship":
                target = first_string_arg(right, src)
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
        recorded in pass-1 into ``RELATES_TO`` edges. A ``relationship("Post")``
        resolves to the model whose class is ``Post``; a ``ForeignKey("users.id")``
        to the model whose table is ``users``. Ambiguous class names (same name
        in two files) are left unresolved (ADR-0004 — never guess)."""
        models = await framework_models(store, self.name)
        index = ModelIndex(models)
        prov = Provenance.resolved(f"pack:{self.name}@{self.version}", commit)
        return relations_to_edges(models, index, _resolve_target, prov)


def _resolve_target(rel: dict[str, str], index: ModelIndex) -> str | None:
    """Resolve one SQLAlchemy relation to a target model id (unique match only)."""
    target = str(rel.get("target", ""))
    if not target:
        return None
    if rel.get("kind") == "fk":
        # "users.id" / "schema.users.id" -> the table segment (second-to-last)
        parts = target.split(".")
        return index.unique_table(parts[-2] if len(parts) >= 2 else parts[0])
    # relationship("Post") / "module.Post" -> bare class name
    return index.unique_class(target.rsplit(".", 1)[-1])


SQLALCHEMY_PACK = SQLAlchemyPack()
