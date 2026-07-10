"""feat-016 chunk 1: the docs staleness join + the DirtySet "docs" consumer."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.core import NodeKind
from agentforge_graph.docgen import (
    DOC_LANG_VERSION,
    DOCS_CONSUMER,
    DocArtifact,
    DocType,
    Footnote,
    SymbolRef,
    is_stale,
    stale_docs,
)
from agentforge_graph.docgen.staleness import DOCS_CONSUMER as CONST
from agentforge_graph.ingest.incremental.dirty import DirtySet


def _doc(path: str, source_ids: tuple[str, ...], commit: str = "abc") -> DocArtifact:
    ref = SymbolRef(id=source_ids[0], kind=NodeKind.FUNCTION, name="f")
    return DocArtifact(
        type=DocType.COMPONENT,
        path=path,
        status="draft",
        synced_commit=commit,
        doc_lang_version=DOC_LANG_VERSION,
        source_ids=source_ids,
        footnotes=(Footnote(marker="f1", ref=ref),),
    )


def test_docs_consumer_name() -> None:
    assert DOCS_CONSUMER == "docs" == CONST


def test_is_stale_on_dirty_intersection() -> None:
    doc = _doc("x.md", ("s1", "s2"))
    assert is_stale(doc, {"s2"}, head_commit="abc") is True
    assert is_stale(doc, {"other"}, head_commit="abc") is False


def test_is_stale_on_commit_moved() -> None:
    doc = _doc("x.md", ("s1",), commit="abc")
    assert is_stale(doc, set(), head_commit="def") is True  # index moved on
    assert is_stale(doc, set(), head_commit="abc") is False
    assert is_stale(doc, set(), head_commit="") is False  # unknown head → not stale


def test_stale_docs_worklist() -> None:
    a = _doc("a.md", ("s1", "s2"))
    b = _doc("b.md", ("s3",))
    c = _doc("c.md", ("s4",))
    got = stale_docs([a, b, c], ["s2", "s3"])
    assert {d.path for d in got} == {"a.md", "b.md"}
    assert stale_docs([a, b, c], []) == []  # nothing dirty → empty


async def test_dirtyset_fans_to_docs_consumer(tmp_path: Path) -> None:
    ds = DirtySet(tmp_path)
    assert "docs" in DirtySet.DEFAULT_CONSUMERS
    await ds.add(["s1", "s2"])
    assert set(await ds.dirty_for("docs")) == {"s1", "s2"}
    await ds.mark_clean("docs", ["s1"])
    assert await ds.dirty_for("docs") == ["s2"]
