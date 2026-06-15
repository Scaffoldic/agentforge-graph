"""Symbol ranking: PageRank surfaces the most-called symbol; focus re-ranks."""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.config import _default_edge_weights
from agentforge_graph.core import NodeKind
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.repomap.rank import rank_symbols

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
_KINDS = [NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD]


@pytest.fixture
async def cg(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    graph = await CodeGraph.index(repo_path=repo)  # CALLS edges resolved at index
    try:
        yield graph
    finally:
        await graph.close()


async def test_most_called_symbol_ranks_top(cg: CodeGraph) -> None:
    ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    assert ranked
    # square() is called by cube() and area() -> highest in-degree -> top rank
    assert ranked[0].name == "square"
    assert ranked[0].signature.startswith("def square")


async def test_ranks_are_sorted_descending(cg: CodeGraph) -> None:
    ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    ranks = [r.rank for r in ranked]
    assert ranks == sorted(ranks, reverse=True)


async def test_focus_reranks_toward_focus_file(cg: CodeGraph) -> None:
    base = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    focused = await rank_symbols(
        cg.store, _KINDS, 0.85, _default_edge_weights(), focus=["shapes.py"]
    )
    # a shapes.py symbol gains rank-share under focus on shapes.py
    circle_base = next(r.rank for r in base if r.name == "Circle")
    circle_focus = next(r.rank for r in focused if r.name == "Circle")
    assert circle_focus > circle_base


async def test_scope_restricts_symbols(cg: CodeGraph) -> None:
    ranked = await rank_symbols(
        cg.store, _KINDS, 0.85, _default_edge_weights(), scope="mathutils.py"
    )
    assert {r.name for r in ranked} == {"square", "cube"}


async def test_signatures_present(cg: CodeGraph) -> None:
    ranked = await rank_symbols(cg.store, _KINDS, 0.85, _default_edge_weights())
    assert all(r.signature for r in ranked)  # every symbol has its def/class line


# --- ENH-007: public-API bias ----------------------------------------------


def test_privacy_classification() -> None:
    from agentforge_graph.repomap.rank import (
        _is_private_module,
        _is_private_name,
        _privacy_multiplier,
    )

    assert _is_private_name("_helper")  # leading underscore -> private
    assert _is_private_name("__mangled")
    assert not _is_private_name("Command")
    assert not _is_private_name("__init__")  # dunder -> public protocol
    assert not _is_private_name("__call__")

    assert _is_private_module("click/_compat.py")  # _-prefixed module -> internal
    assert _is_private_module("_winconsole.py")
    assert not _is_private_module("click/core.py")
    assert not _is_private_module("pkg/__init__.py")  # package root -> public

    assert _privacy_multiplier("_x", "a.py", 0.0) == 1.0  # bias off -> no change
    assert _privacy_multiplier("_x", "a.py", 0.5) == 0.5  # private name demoted
    assert _privacy_multiplier("x", "_m.py", 0.5) == 0.5  # private module demoted
    assert _privacy_multiplier("x", "a.py", 0.5) == 1.0  # public untouched


@pytest.fixture
async def bias_cg(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    # `process` and `_process` have IDENTICAL centrality (each called twice), so
    # any ordering shift between them is due solely to the public-API bias.
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "api.py").write_text(
        "def process(x):\n    return x\n\n"
        "def _process(x):\n    return x\n\n"
        "def c1():\n    return process(1) + _process(1)\n\n"
        "def c2():\n    return process(2) + _process(2)\n"
    )
    graph = await CodeGraph.index(repo_path=repo)
    try:
        yield graph
    finally:
        await graph.close()


async def test_public_bias_demotes_private_peer(bias_cg: CodeGraph) -> None:
    weights = _default_edge_weights()

    def rank_of(ranked: list, name: str) -> float:
        return next(r.rank for r in ranked if r.name == name)

    neutral = await rank_symbols(bias_cg.store, _KINDS, 0.85, weights, public_bias=0.0)
    # equal centrality -> identical rank when the bias is off
    assert rank_of(neutral, "process") == pytest.approx(rank_of(neutral, "_process"))

    biased = await rank_symbols(bias_cg.store, _KINDS, 0.85, weights, public_bias=0.5)
    # with the bias on, the public peer outranks the private one (ordering shift)
    assert rank_of(biased, "process") > rank_of(biased, "_process")
    order = [r.name for r in biased]
    assert order.index("process") < order.index("_process")
    # the public symbol's own rank is unchanged; only the private one is demoted
    assert rank_of(biased, "process") == pytest.approx(rank_of(neutral, "process"))
    assert rank_of(biased, "_process") < rank_of(neutral, "_process")
