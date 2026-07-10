"""feat-016 chunk 6: the `ckg docs` CLI surface.

CLI tests are sync (``main`` runs its own event loop); async fixtures seed the
index + a doc using a repeating const LLMClient (no creds), mirroring the
feat-015 query CLI tests.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from agentforge_core.contracts.llm import LLMClient
from agentforge_core.values.messages import LLMResponse, Message, TokenUsage, ToolSpec

from agentforge_graph.cli import main
from agentforge_graph.docgen import get_recipe
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


@pytest.fixture
async def indexed(tmp_path: Path) -> AsyncIterator[Path]:
    (tmp_path / "app.py").write_text(_SRC)
    cg = await CodeGraph.index(repo_path=tmp_path)
    await cg.close()
    yield tmp_path


@pytest.fixture
async def seeded(tmp_path: Path) -> AsyncIterator[tuple[Path, str]]:
    (tmp_path / "app.py").write_text(_SRC)
    cg = await CodeGraph.index(repo_path=tmp_path)
    try:
        pack = await get_recipe(DocType.ARCHITECTURE).seed(cg, DocTarget(type=DocType.ARCHITECTURE))
        sid = pack.facts[0].ref.id
        doc = f"## Overview\n\nCentral [^f1].\n\n## References\n\n[^f1]: {sid}\n"
        art = await cg.docs_generate("architecture", model=_ConstLLM(doc))
    finally:
        await cg.close()
    yield tmp_path, art.path


def test_generate_requires_type_or_all(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["docs", "generate", "--path", str(indexed)])
    assert rc == 2
    assert "--type or --all" in capsys.readouterr().err


def test_generate_refuses_when_disabled(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (indexed / "ckg.yaml").write_text("docgen:\n  enabled: false\n")
    rc = main(
        [
            "docs",
            "generate",
            "--type",
            "architecture",
            "--path",
            str(indexed),
            "--config",
            str(indexed / "ckg.yaml"),
        ]
    )
    assert rc == 2
    assert "disabled" in capsys.readouterr().err


def test_list_shows_generated_doc(
    seeded: tuple[Path, str], capsys: pytest.CaptureFixture[str]
) -> None:
    repo, docpath = seeded
    rc = main(["docs", "list", "--path", str(repo), "--format", "json"])
    assert rc == 0
    out = capsys.readouterr().out
    assert docpath in out
    assert "architecture" in out


def test_promote_via_cli(seeded: tuple[Path, str], capsys: pytest.CaptureFixture[str]) -> None:
    repo, docpath = seeded
    rc = main(["docs", "promote", docpath, "--path", str(repo)])
    assert rc == 0
    assert "promoted" in capsys.readouterr().out
    # reflected in a subsequent list
    assert main(["docs", "list", "--path", str(repo)]) == 0
    assert "accepted" in capsys.readouterr().out


def test_diff_unknown_doc_errors(indexed: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["docs", "diff", "docs/_generated/nope.md", "--path", str(indexed)])
    assert rc == 2
    assert "no generated doc" in capsys.readouterr().err
