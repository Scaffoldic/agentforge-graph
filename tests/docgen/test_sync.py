"""feat-016 chunk 7: the opt-in sync flywheel + anti-echo-chamber guarantee."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from agentforge_core.contracts.llm import LLMClient
from agentforge_core.values.messages import LLMResponse, Message, TokenUsage, ToolSpec

from agentforge_graph.core import EdgeKind, GraphQuery, NodeKind, Source
from agentforge_graph.docgen import get_recipe
from agentforge_graph.docgen.errors import DocgenError, PromoteRequired
from agentforge_graph.docgen.types import DocTarget, DocType
from agentforge_graph.ingest import CodeGraph

_SRC = """\
class Repo:
    def save(self):
        return validate()


def validate():
    return True
"""


class _ConstLLM(LLMClient):
    def __init__(self, doc: str) -> None:
        self._doc = doc

    async def call(
        self, system: str, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> LLMResponse:
        del system, messages, tools
        return LLMResponse(
            content=self._doc,
            tool_calls=(),
            stop_reason="end_turn",
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            cost_usd=0.0,
            model="const",
            provider="const",
        )

    async def close(self) -> None:
        return


async def _generate(cg: CodeGraph, *, promote: bool) -> str:
    pack = await get_recipe(DocType.ARCHITECTURE).seed(cg, DocTarget(type=DocType.ARCHITECTURE))
    sid = pack.facts[0].ref.id
    doc = f"## Overview\n\nCentral [^f1].\n\n## References\n\n[^f1]: {sid}\n"
    art = await cg.docs_generate("architecture", model=_ConstLLM(doc))
    if promote:
        cg.docs_promote(art.path)
    return sid


async def _open(tmp_path: Path, cfg: str) -> AsyncIterator[CodeGraph]:
    (tmp_path / "app.py").write_text(_SRC)
    (tmp_path / "ckg.yaml").write_text(cfg)
    cg = await CodeGraph.index(repo_path=tmp_path, config=str(tmp_path / "ckg.yaml"))
    return cg


async def test_sync_refuses_when_round_trip_off(tmp_path: Path) -> None:
    cg = await _open(tmp_path, "docgen:\n  enabled: true\n")  # round_trip defaults off
    try:
        await _generate(cg, promote=True)
        with pytest.raises(DocgenError, match="round_trip"):
            await cg.docs_sync()
    finally:
        await cg.close()


async def test_sync_refuses_unpromoted(tmp_path: Path) -> None:
    cg = await _open(tmp_path, "docgen:\n  round_trip: true\n")
    try:
        await _generate(cg, promote=False)  # a draft, not accepted
        with pytest.raises(PromoteRequired):
            await cg.docs_sync()
    finally:
        await cg.close()


async def test_sync_creates_llm_doc_chunk_with_describes(tmp_path: Path) -> None:
    cg = await _open(tmp_path, "docgen:\n  round_trip: true\nembed:\n  enabled: false\n")
    try:
        sid = await _generate(cg, promote=True)
        assert await cg.docs_sync() == 1

        nodes = (
            await cg.store.graph.query(GraphQuery(kinds=[NodeKind.DOC_CHUNK], limit=1000))
        ).nodes
        gen = [n for n in nodes if n.attrs.get("doc_source") == "generated"]
        assert len(gen) == 1
        # anti-echo-chamber: the synced doc is llm-sourced ...
        assert gen[0].provenance.source is Source.LLM
        # ... and DESCRIBES the symbol it cited
        desc = await cg.store.graph.adjacent(gen[0].id, [EdgeKind.DESCRIBES], "out")
        assert {e.dst for e in desc} == {sid}

        # ... so a >= parsed floor never surfaces it as a citable fact
        floored = (
            await cg.store.graph.query(
                GraphQuery(kinds=[NodeKind.DOC_CHUNK], min_source=Source.PARSED, limit=1000)
            )
        ).nodes
        assert all(n.attrs.get("doc_source") != "generated" for n in floored)
    finally:
        await cg.close()


async def test_sync_embeds_with_fake_embedder(tmp_path: Path) -> None:
    cg = await _open(tmp_path, "docgen:\n  round_trip: true\nembed:\n  driver: fake\n")
    try:
        await _generate(cg, promote=True)
        # exercises the embed path (fake embedder, no creds) without error
        assert await cg.docs_sync() == 1
    finally:
        await cg.close()
