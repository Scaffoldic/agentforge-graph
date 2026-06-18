"""feat-010 follow-up: general Markdown docs under ``knowledge.doc_globs`` become
DocChunks that DESCRIBE the code they unambiguously mention — broadening doc
coverage beyond ADRs (READMEs, guides). Per-file, so edits/deletes ride feat-004."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, SymbolID
from agentforge_graph.ingest import CodeGraph

_CONFIG = "knowledge:\n  enabled: on\n  doc_globs:\n    - '**/*.md'\n"


def _write_repo(repo: Path) -> None:
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "payments.py").write_text(
        "class PaymentService:\n    def charge(self, amount):\n        return amount\n"
    )
    (repo / "README.md").write_text(
        "# My Project\n\nThe entrypoint is `src/payments.py`.\n\n"
        "## Billing\n\nBilling goes through `PaymentService`.\n"
    )
    (repo / "ckg.yaml").write_text(_CONFIG)


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    repo = tmp_path / "proj"
    _write_repo(repo)
    cg = await CodeGraph.index(repo_path=repo, config=repo / "ckg.yaml")
    try:
        yield cg, repo
    finally:
        await cg.close()


async def _doc_chunks(cg: CodeGraph, source: str | None = None) -> list[object]:
    nodes = (await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=999))).nodes
    return [n for n in nodes if source is None or n.attrs.get("doc_source") == source]


async def test_general_doc_creates_describing_docchunks(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    assert cg.stats().docs_indexed == 1  # README.md
    docs = await _doc_chunks(cg, source="doc")
    assert docs  # one DocChunk per README section
    # the "Billing" section DESCRIBES PaymentService (unambiguous name mention)
    described: set[str] = set()
    for d in docs:
        for e in await cg.store.graph.adjacent(d.id, [EdgeKind.DESCRIBES], "out"):
            described.add(SymbolID.parse(e.dst).descriptor)
    assert "PaymentService#" in described


async def test_describes_resolves_path_and_name(graph: tuple[CodeGraph, Path]) -> None:
    cg, _ = graph
    assert cg.stats().describes_resolved >= 2  # the file path + PaymentService name


async def test_adr_not_double_ingested_as_doc(tmp_path: Path) -> None:
    # an ADR under docs/adr matched by doc_globs must NOT become a general DocChunk
    repo = tmp_path / "proj2"
    _write_repo(repo)
    adr = repo / "docs" / "adr"
    adr.mkdir(parents=True)
    (adr / "0001-x.md").write_text("# 1. Use idempotency\n\n## Status\n\nAccepted\n")
    cg = await CodeGraph.index(repo_path=repo, config=repo / "ckg.yaml")
    try:
        doc_paths = {SymbolID.parse(d.id).path for d in await _doc_chunks(cg, source="doc")}
        assert "docs/adr/0001-x.md" not in doc_paths  # handled by the ADR pass, not docs
        assert cg.stats().decisions_indexed == 1
    finally:
        await cg.close()


async def test_deleted_doc_is_gced(graph: tuple[CodeGraph, Path]) -> None:
    cg, repo = graph
    assert await _doc_chunks(cg, source="doc")
    (repo / "README.md").unlink()
    await cg.refresh()
    assert await _doc_chunks(cg, source="doc") == []
