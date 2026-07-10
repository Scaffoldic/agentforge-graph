"""feat-016 chunk 5: dirty-aware update + list/diff/promote."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from agentforge_core.contracts.llm import LLMClient
from agentforge_core.values.messages import LLMResponse, Message, TokenUsage, ToolSpec

from agentforge_graph.config import DocGenConfig, StoreConfig
from agentforge_graph.docgen import DocGenerator, get_recipe
from agentforge_graph.docgen.errors import DocgenError
from agentforge_graph.docgen.staleness import DOCS_CONSUMER
from agentforge_graph.docgen.types import STATUS_ACCEPTED, DocTarget, DocType
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.ingest.incremental import DirtySet
from agentforge_graph.store import resolve_root

_SRC = """\
class Repo:
    def save(self):
        return validate()


def validate():
    return True
"""


class _ConstLLM(LLMClient):
    """A repeating LLMClient (unlike MockLLMClient, never exhausts) — returns the
    same end_turn document for every call, so multi-compose flows (update/diff)
    stay deterministic and creds-free."""

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


@pytest.fixture
async def env(tmp_path: Path) -> AsyncIterator[tuple[CodeGraph, Path]]:
    (tmp_path / "app.py").write_text(_SRC)
    cg = await CodeGraph.index(repo_path=tmp_path)
    yield cg, tmp_path
    await cg.close()


async def _gen(cg: CodeGraph, repo: Path) -> tuple[DocGenerator, str]:
    pack = await get_recipe(DocType.ARCHITECTURE).seed(cg, DocTarget(type=DocType.ARCHITECTURE))
    sid = pack.facts[0].ref.id
    doc = f"## Overview\n\nCentral symbol [^f1].\n\n## References\n\n[^f1]: {sid}\n"
    return DocGenerator(cg, DocGenConfig(), repo_path=repo, model=_ConstLLM(doc)), sid


async def test_update_regenerates_only_dirty_docs(env: tuple[CodeGraph, Path]) -> None:
    cg, repo = env
    gen, sid = await _gen(cg, repo)
    art = await gen.generate(DocTarget(type=DocType.ARCHITECTURE))

    # nothing dirty yet → update is a no-op
    assert await gen.update() == []

    # dirty a symbol the doc grounds on → update regenerates that doc
    dirty = DirtySet(resolve_root(repo, StoreConfig.load(None)))
    await dirty.add([sid])
    regenerated = await gen.update()
    assert [a.path for a in regenerated] == [art.path]

    # the covered dirty id is now marked clean for the docs consumer
    assert sid not in await DirtySet(resolve_root(repo, StoreConfig.load(None))).dirty_for(
        DOCS_CONSUMER
    )


async def test_list_docs_flags_stale(env: tuple[CodeGraph, Path]) -> None:
    cg, repo = env
    gen, sid = await _gen(cg, repo)
    await gen.generate(DocTarget(type=DocType.ARCHITECTURE))

    fresh = await gen.list_docs()
    assert len(fresh) == 1 and fresh[0].stale is False

    await DirtySet(resolve_root(repo, StoreConfig.load(None))).add([sid])
    listed = await gen.list_docs()
    assert listed[0].stale is True


async def test_promote_flips_status(env: tuple[CodeGraph, Path]) -> None:
    cg, repo = env
    gen, _ = await _gen(cg, repo)
    art = await gen.generate(DocTarget(type=DocType.ARCHITECTURE))
    promoted = gen.promote(art.path)
    assert promoted.status == STATUS_ACCEPTED
    assert (await gen.list_docs())[0].status == STATUS_ACCEPTED


async def test_promote_unknown_path_raises(env: tuple[CodeGraph, Path]) -> None:
    cg, repo = env
    gen, _ = await _gen(cg, repo)
    with pytest.raises(DocgenError, match="no generated doc"):
        gen.promote("docs/_generated/nope.md")


async def test_diff_detects_on_disk_edit(env: tuple[CodeGraph, Path]) -> None:
    cg, repo = env
    gen, _ = await _gen(cg, repo)
    art = await gen.generate(DocTarget(type=DocType.ARCHITECTURE))

    # freshly generated == a deterministic regeneration → empty diff
    assert await gen.diff(art.path) == ""

    # a human edit shows up in the diff
    (repo / art.path).write_text("## Overview\n\nHand-edited nonsense.\n")
    d = await gen.diff(art.path)
    assert "Hand-edited nonsense" in d
    assert "Central symbol" in d  # what regeneration would restore
