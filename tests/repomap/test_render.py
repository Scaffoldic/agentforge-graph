"""Budget render + RepoMap facade."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.chunking import estimate_tokens
from agentforge_graph.config import RepoMapConfig
from agentforge_graph.core import NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.repomap import RankedSymbol, RepoMap, render_map

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"


def _sym(name: str, path: str, rank: float, sig: str) -> RankedSymbol:
    return RankedSymbol(
        id=f"ckg py r {path} {name}().",
        name=name,
        kind=NodeKind.FUNCTION,
        path=path,
        rank=rank,
        signature=sig,
    )


def test_render_groups_by_file_and_orders_by_rank() -> None:
    ranked = [
        _sym("a", "z.py", 0.9, "def a():"),
        _sym("b", "y.py", 0.5, "def b():"),
        _sym("c", "z.py", 0.4, "def c():"),
    ]
    out = render_map(ranked, budget_tokens=10_000)
    # z.py (highest-ranked symbol) comes first, with both its symbols grouped
    assert out.index("z.py:") < out.index("y.py:")
    assert out.index("def a():") < out.index("def c():")


def test_budget_never_exceeded_excluding_note() -> None:
    ranked = [_sym(f"f{i}", "m.py", 1.0 - i * 0.01, f"def f{i}(x, y):") for i in range(50)]
    budget = 30
    out = render_map(ranked, budget_tokens=budget)
    content = "\n".join(ln for ln in out.splitlines() if not ln.startswith("… "))
    assert estimate_tokens(content) <= budget


def test_truncation_note_present_when_truncated() -> None:
    ranked = [_sym(f"f{i}", "m.py", 1.0, f"def f{i}():") for i in range(40)]
    out = render_map(ranked, budget_tokens=15)
    assert "more symbols below the budget" in out


def test_no_note_when_everything_fits() -> None:
    ranked = [_sym("a", "z.py", 0.9, "def a():")]
    out = render_map(ranked, budget_tokens=10_000)
    assert "below the budget" not in out


def test_missing_signature_degrades() -> None:
    ranked = [_sym("a", "z.py", 0.9, "")]
    out = render_map(ranked, budget_tokens=1000)
    assert "a(...)" in out


@pytest.fixture
async def repomap(tmp_path: Path) -> AsyncIterator[RepoMap]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield RepoMap(cg.store, RepoMapConfig())
    finally:
        await cg.close()


async def test_facade_render(repomap: RepoMap) -> None:
    text = await repomap.render(budget_tokens=2000)
    assert "mathutils.py:" in text
    assert "def square" in text


async def test_facade_ranked_symbols_top_k(repomap: RepoMap) -> None:
    top = await repomap.ranked_symbols(k=2)
    assert len(top) == 2
    assert top[0].name == "square"  # most-called
