"""Django framework pack (feat-011) — ORM models.

Extracts Django model classes into ``DataModel`` nodes + ``HAS_FIELD`` edges to
each mapped field (a ``Variable`` carrying its field type, e.g. ``CharField``).
A class is treated as a model only with declarative evidence — a base whose
tail is ``Model`` (``class X(models.Model)``) or at least one ``models.*Field``
assignment (which also catches abstract-base subclasses) — so plain classes in
a Django app never mint false models (ADR-0004).

``ForeignKey`` / ``OneToOneField`` / ``ManyToManyField`` targets (a model class,
a ``"app.Model"`` string, or ``"self"``) are recorded in pass-1 and stitched
into cross-file ``RELATES_TO`` edges in pass-2 against the whole-repo model set
(unique-match-only). FK/O2O are also a ``HAS_FIELD`` column; M2M is relation-
only. The table name comes from ``class Meta: db_table`` when set (Django's
``app_label``-derived default is not known statically).
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
    base_classes,
    callee_name,
    class_body,
    dotted_tail,
    first_positional_arg,
    iter_class_assignments,
    python_language,
    strip_quotes,
    text,
)

_HERE = Path(__file__).parent
# relation field types -> RELATES_TO kind; FK/O2O also produce a column. Note
# `ForeignKey` does NOT end in `Field`, so relation calls are matched by name.
_RELATION_FIELDS = {"ForeignKey": "fk", "OneToOneField": "o2o", "ManyToManyField": "m2m"}


@cache
def _query_text() -> str:
    return (_HERE / "models.scm").read_text(encoding="utf-8")


def _is_field_call(callee: str) -> bool:
    """A Django model field: any ``*Field`` class plus the relation classes
    (``ForeignKey`` ends in ``Key``, not ``Field``)."""
    return callee.endswith("Field") or callee in _RELATION_FIELDS


def _is_models_namespaced_field(call: TSNode, src: bytes) -> bool:
    """True for ``models.CharField(...)`` / ``models.ForeignKey(...)`` — a field
    call whose receiver tail is ``models``. The namespace check keeps a non-Django
    ``SomeField()`` from looking like model evidence."""
    if not _is_field_call(callee_name(call, src)):
        return False
    fn = call.child_by_field_name("function")
    if fn is None or fn.type != "attribute":
        return False
    obj = fn.child_by_field_name("object")
    return obj is not None and dotted_tail(obj, src) == "models"


def _relation_target(call: TSNode, src: bytes, self_name: str) -> str:
    """The related model name from a relation field's first positional arg:
    ``User`` for ``ForeignKey(User)`` / ``ForeignKey("app.User")``; the class's
    own name for ``"self"``; "" when non-literal/absent."""
    arg = first_positional_arg(call, src)
    if arg is None:
        return ""
    if arg.type == "string":
        target = strip_quotes(text(arg, src)).rsplit(".", 1)[-1]
        return self_name if target == "self" else target
    return dotted_tail(arg, src)


def _meta_db_table(body: TSNode, src: bytes) -> str | None:
    """``db_table`` from an inner ``class Meta``, or None."""
    for stmt in body.named_children:
        if stmt.type != "class_definition":
            continue
        name = stmt.child_by_field_name("name")
        if name is None or text(name, src) != "Meta":
            continue
        meta_body = class_body(stmt)
        if meta_body is None:
            continue
        for fname, _assign, right in iter_class_assignments(meta_body, src):
            if fname == "db_table" and right.type == "string":
                return strip_quotes(text(right, src))
    return None


class DjangoPack(FrameworkPack):
    name = "django"
    language = "python"
    language_slug = "py"  # SymbolID slug — must match the Python language pack
    version = "1"
    dep_names = ("django",)
    import_markers = ("import django", "from django")

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

        has_model_base = any(b == "Model" for b in base_classes(class_node, src))
        fields: list[tuple[str, str, TSNode]] = []  # (name, field_type, assignment node)
        relations: list[dict[str, str]] = []
        has_models_field = False
        for field_name, assign, right in iter_class_assignments(body, src):
            if right.type != "call":
                continue
            callee = callee_name(right, src)
            if not _is_field_call(callee):
                continue
            if _is_models_namespaced_field(right, src):
                has_models_field = True
            kind = _RELATION_FIELDS.get(callee)
            if kind is not None:
                target = _relation_target(right, src, class_name)
                if target:
                    relations.append({"field": field_name, "target": target, "kind": kind})
                if kind != "m2m":  # FK/O2O carry a real column; M2M does not
                    fields.append((field_name, callee, assign))
            else:
                fields.append((field_name, callee, assign))

        # Conservative: a class is a model only with declarative evidence.
        if not (has_model_base or has_models_field):
            return

        table = _meta_db_table(body, src)
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
        for field_name, field_type, assign in fields:
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
                    attrs={"column_type": field_type, "framework": self.name},
                    provenance=prov,
                )
            )
            facts.edges.append(
                Edge(src=model_id, dst=field_id, kind=EdgeKind.HAS_FIELD, provenance=prov)
            )

    async def resolve(self, store: GraphStore, commit: str = "") -> list[Edge]:
        """Pass-2: stitch ``ForeignKey``/``OneToOneField``/``ManyToManyField``
        targets into ``RELATES_TO`` edges. Django targets are model class names,
        so every relation resolves via the class index (unique match only)."""
        models = await framework_models(store, self.name)
        index = ModelIndex(models)
        prov = Provenance.resolved(f"pack:{self.name}@{self.version}", commit)
        return relations_to_edges(models, index, _resolve_target, prov)


def _resolve_target(rel: dict[str, str], index: ModelIndex) -> str | None:
    """Resolve one Django relation to a target model id (unique class match)."""
    return index.unique_class(str(rel.get("target", "")).rsplit(".", 1)[-1])


DJANGO_PACK = DjangoPack()
