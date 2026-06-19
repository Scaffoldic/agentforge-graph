"""Django pack golden tests (feat-011): DataModel + HAS_FIELD extraction, the
abstract-base / models-namespace model evidence, Meta db_table, the conservative
non-model guard, and pass-1 FK/O2O/M2M relation recording."""

from __future__ import annotations

import hashlib
from pathlib import Path

from agentforge_graph.core import EdgeKind, NodeKind, SourceFile
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.django import DJANGO_PACK

FIXTURES = Path(__file__).parent / "fixtures" / "django"


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
    return DJANGO_PACK.extract(_sf("models.py"), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(DJANGO_PACK, FrameworkPack)
    assert DJANGO_PACK.name == "django"
    assert DJANGO_PACK.language == "python" and DJANGO_PACK.language_slug == "py"


def test_models_extracted() -> None:
    facts = _facts()
    models = {n.name: n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    # User's table comes from Meta.db_table; the others have no static table name
    assert set(models) == {"TimestampedModel", "auth_user", "Tag", "Post"}
    assert models["auth_user"].attrs["table"] == "auth_user"
    assert models["auth_user"].attrs["model_class"] == "User"
    # Post inherits the abstract base (not `models.Model`) but has models.* fields
    assert models["Post"].attrs["model_class"] == "Post"
    assert "table" not in models["Post"].attrs


def test_has_field_edges_exclude_m2m() -> None:
    facts = _facts()
    models = {n.id: n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    fields = {n.id: n for n in facts.nodes if n.kind is NodeKind.VARIABLE}
    by_model: dict[str, set[str]] = {}
    for e in facts.edges:
        if e.kind is EdgeKind.HAS_FIELD:
            by_model.setdefault(models[e.src].name, set()).add(fields[e.dst].name)
    assert by_model["auth_user"] == {"name", "email"}
    # FK `author` is a column; M2M `tags` is relation-only (no column)
    assert by_model["Post"] == {"title", "author"}


def test_field_types_are_django_field_classes() -> None:
    facts = _facts()
    types = {n.name: n.attrs.get("column_type") for n in facts.nodes if n.kind is NodeKind.VARIABLE}
    assert types["name"] == "CharField"
    assert types["author"] == "ForeignKey"


def test_relations_recorded_fk_and_m2m() -> None:
    facts = _facts()
    post = next(
        n
        for n in facts.nodes
        if n.kind is NodeKind.DATA_MODEL and n.attrs.get("model_class") == "Post"
    )
    rels = post.attrs["relations"]
    assert {"field": "author", "target": "User", "kind": "fk"} in rels
    assert {"field": "tags", "target": "Tag", "kind": "m2m"} in rels
    assert facts.unresolved == 0


def test_self_reference_target_is_the_class() -> None:
    facts = DJANGO_PACK.extract(
        _src(
            "from django.db import models\n\n"
            "class Node(models.Model):\n"
            "    parent = models.ForeignKey('self', on_delete=models.CASCADE)\n"
        ),
        repo="fixture",
        commit="c0",
    )
    node = next(n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL)
    assert node.attrs["relations"] == [{"field": "parent", "target": "Node", "kind": "fk"}]


def test_string_target_app_label_stripped() -> None:
    facts = DJANGO_PACK.extract(
        _src(
            "from django.db import models\n\n"
            "class Post(models.Model):\n"
            "    author = models.ForeignKey('auth.User', on_delete=models.CASCADE)\n"
        ),
        repo="fixture",
        commit="c0",
    )
    post = next(n for n in facts.nodes if n.kind is NodeKind.DATA_MODEL)
    assert post.attrs["relations"] == [{"field": "author", "target": "User", "kind": "fk"}]


def test_plain_class_and_forms_field_are_not_models() -> None:
    facts = _facts()
    assert "PlainThing" not in {n.name for n in facts.nodes if n.kind is NodeKind.DATA_MODEL}
    # a forms.CharField (not models.*) on a base-less class is not model evidence
    forms = DJANGO_PACK.extract(
        _src("from django import forms\n\nclass F:\n    name = forms.CharField()\n"),
        repo="fixture",
        commit="c0",
    )
    assert [n for n in forms.nodes if n.kind is NodeKind.DATA_MODEL] == []


def test_no_models_on_plain_file() -> None:
    facts = DJANGO_PACK.extract(_src("def f():\n    return 1\n"), repo="fixture", commit="c0")
    assert facts.nodes == [] and facts.edges == [] and facts.unresolved == 0
