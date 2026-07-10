"""feat-016 chunk 1: docgen value types."""

from __future__ import annotations

from agentforge_graph.core import NodeKind
from agentforge_graph.docgen import (
    DOC_LANG_VERSION,
    STATUS_ACCEPTED,
    STATUS_DRAFT,
    DocArtifact,
    DocTarget,
    DocType,
    Footnote,
    GroundedFact,
    GroundedPack,
    ProvenanceSet,
    SymbolRef,
)


def _ref(sid: str, name: str = "f") -> SymbolRef:
    return SymbolRef(id=sid, kind=NodeKind.FUNCTION, name=name, path="a.py", span=(1, 3))


def test_doc_type_values() -> None:
    assert DocType("ai-context") is DocType.AI_CONTEXT
    assert {t.value for t in DocType} == {"ai-context", "architecture", "component", "design"}


def test_doc_lang_version_is_set() -> None:
    assert DOC_LANG_VERSION == "1.0"


def test_provenance_set_build_and_contains() -> None:
    seed = {"s1": _ref("s1")}
    tools = {"t1": _ref("t1"), "s1": _ref("s1", name="dup")}
    ps = ProvenanceSet.build(seed, tools)
    assert ps.contains("s1") and ps.contains("t1")
    assert not ps.contains("missing")
    # earlier group (seed) wins the collision
    assert ps.refs["s1"].name == "f"
    assert ps.source_ids() == ("s1", "t1")  # sorted


def test_grounded_pack_defaults() -> None:
    pack = GroundedPack(target=DocTarget(type=DocType.ARCHITECTURE))
    assert pack.facts == () and pack.notes == ()


def test_grounded_fact_carries_ref_and_source() -> None:
    f = GroundedFact(text="Repo.save persists", ref=_ref("s1", "save"), source="parsed")
    assert f.ref.name == "save" and f.source == "parsed"


def test_doc_artifact_accepted_flag() -> None:
    base = dict(
        type=DocType.ARCHITECTURE,
        path="docs/_generated/architecture.md",
        synced_commit="abc123",
        doc_lang_version=DOC_LANG_VERSION,
        source_ids=("s1",),
        footnotes=(Footnote(marker="f1", ref=_ref("s1")),),
    )
    draft = DocArtifact(status=STATUS_DRAFT, **base)
    accepted = DocArtifact(status=STATUS_ACCEPTED, **base)
    assert draft.accepted is False
    assert accepted.accepted is True
    assert draft.stale is False  # default, computed later
