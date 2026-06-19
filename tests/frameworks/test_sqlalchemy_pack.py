"""SQLAlchemy pack golden tests (feat-011): DataModel + HAS_FIELD extraction,
the conservative non-model guard, pass-1 relation recording, and the pass-2
RELATES_TO target resolution — asserted directly on FrameworkFacts / helpers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile, SymbolID
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.orm import ModelIndex
from agentforge_graph.frameworks.packs.sqlalchemy import SQLALCHEMY_PACK, _resolve_target

FIXTURES = Path(__file__).parent / "fixtures" / "sqlalchemy"


def _sf(name: str) -> SourceFile:
    raw = (FIXTURES / name).read_bytes()
    return SourceFile(
        path=name, text=raw.decode(), language="py", content_hash=hashlib.sha256(raw).hexdigest()
    )


def _src(text: str) -> SourceFile:
    return SourceFile(
        path="m.py",
        text=text,
        language="py",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts() -> FrameworkFacts:
    return SQLALCHEMY_PACK.extract(_sf("models.py"), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(SQLALCHEMY_PACK, FrameworkPack)
    assert SQLALCHEMY_PACK.name == "sqlalchemy"
    assert SQLALCHEMY_PACK.language == "python" and SQLALCHEMY_PACK.language_slug == "py"


def test_models_extracted_with_tables() -> None:
    facts = _facts()
    models = {n.name: n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    assert set(models) == {"users", "posts"}
    users = models["users"]
    assert users.attrs["table"] == "users"
    assert users.attrs["framework"] == "sqlalchemy"
    # the DataModel links to the underlying class symbol id
    assert SymbolID.parse(str(users.attrs["class"])).descriptor == "User#"
    assert users.span is not None and users.span[0] >= 1


def test_has_field_edges_to_mapped_columns() -> None:
    facts = _facts()
    models = {n.name: n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    fields = {n.id: n for n in facts.nodes if n.kind is NodeKind.VARIABLE}
    by_model: dict[str, set[str]] = {}
    for e in facts.edges:
        if e.kind is EdgeKind.HAS_FIELD:
            model = next(m for m in models.values() if m.id == e.src)
            by_model.setdefault(model.name, set()).add(fields[e.dst].name)
    # relationship() is NOT a column -> not a field; classic + 2.0 columns are
    assert by_model["users"] == {"id", "name"}
    assert by_model["posts"] == {"id", "title", "author_id"}


def test_column_types_captured() -> None:
    facts = _facts()
    types = {n.name: n.attrs.get("column_type") for n in facts.nodes if n.kind is NodeKind.VARIABLE}
    assert types["id"] in {"Integer", "int"}  # classic Integer / Mapped[int]
    assert types["name"] == "String"
    assert types["author_id"] == "Integer"


def test_pending_relations_recorded_on_model_nodes() -> None:
    # pass-1 records relationship/FK targets on the model node for pass-2 to
    # stitch into RELATES_TO; they are NOT counted as unresolved here.
    facts = _facts()
    assert facts.unresolved == 0
    models = {n.name: n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    user_rels = models["users"].attrs["relations"]
    assert {"field": "posts", "target": "Post", "kind": "relationship"} in user_rels
    post_rels = models["posts"].attrs["relations"]
    assert {"field": "author_id", "target": "users.id", "kind": "fk"} in post_rels


def test_resolve_target_unique_match_only() -> None:
    index = ModelIndex([])
    index.by_class = {"Post": {"id:Post"}, "Tag": {"a:Tag", "b:Tag"}}
    index.by_table = {"users": {"id:User"}}
    # relationship by class name (last segment of a dotted target)
    assert _resolve_target({"target": "Post", "kind": "relationship"}, index) == "id:Post"
    assert _resolve_target({"target": "models.Post", "kind": "relationship"}, index) == "id:Post"
    # fk by the table segment of "users.id"
    assert _resolve_target({"target": "users.id", "kind": "fk"}, index) == "id:User"
    # ambiguous class name (two models) -> unresolved (ADR-0004)
    assert _resolve_target({"target": "Tag", "kind": "relationship"}, index) is None
    # external / unknown target -> unresolved
    assert _resolve_target({"target": "Other", "kind": "relationship"}, index) is None


def test_plain_class_is_not_a_model() -> None:
    facts = _facts()
    names = {n.name for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    assert "PlainThing" not in names


def test_model_without_tablename_still_extracted() -> None:
    # an abstract/mixin model: no __tablename__ but real columns -> still a model
    facts = SQLALCHEMY_PACK.extract(
        _src("from sqlalchemy import Column, Integer\n\nclass Mixin:\n    id = Column(Integer)\n"),
        repo="fixture",
        commit="c0",
    )
    models = [n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL]
    assert len(models) == 1
    assert models[0].name == "Mixin" and "table" not in models[0].attrs


def test_no_models_on_plain_file() -> None:
    facts = SQLALCHEMY_PACK.extract(_src("def f():\n    return 1\n"), repo="fixture", commit="c0")
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0
