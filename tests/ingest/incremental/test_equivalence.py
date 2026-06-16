"""The feat-004 correctness contract: an incremental ``refresh`` must produce
the *same* graph as a full re-index of the same final repo state (modulo
provenance timestamps). Runs randomized-ish edit scripts covering add, modify
(incl. symbol rename), and delete, exercising cross-file import resolution and
the resolved-edge invalidation + package GC.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.core import GraphQuery
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.store import Store

_ALL = 10_000_000

# ---- repo states -----------------------------------------------------------

# conv.py carries two same-named top-level callables (overload-style); a caller
# resolves `pick` to exactly one of them. The export name->id map is last-write-
# wins over store.neighbors() order, which is NOT stable across an incremental
# (delete+re-add of a modified file) vs a full insert — so without a
# deterministic tiebreak the CALLS edge would target a different (equally valid)
# overload. This case guards that determinism (a real bug the prior fixtures
# missed: none had same-named defs).
S0 = {
    "m.py": ("def square(x):\n    return x * x\n\n\ndef cube(x):\n    return square(x) * x\n"),
    "conv.py": ("def pick(x):\n    return x\n\n\ndef pick(x, y):\n    return x + y\n"),
    "app.py": (
        "from m import square\nfrom conv import pick\n\n\n"
        "def area(r):\n    return square(r) + pick(r)\n"
    ),
    "legacy.py": "def old():\n    return 1\n",
}

# m.py: cube -> cubed (symbol rename). conv.py: + a third `pick` overload (forces
# a delete+re-add of an overloaded file). app.py: + perimeter. newmod.py added
# (imports m). legacy.py deleted.
S1 = {
    "m.py": ("def square(x):\n    return x * x\n\n\ndef cubed(x):\n    return square(x) * x\n"),
    "conv.py": (
        "def pick(x):\n    return x\n\n\n"
        "def pick(x, y):\n    return x + y\n\n\n"
        "def pick(x, y, z):\n    return x + y + z\n"
    ),
    "app.py": (
        "from m import square\nfrom conv import pick\n\n\n"
        "def area(r):\n    return square(r) + pick(r)\n\n\n"
        "def perimeter(r):\n    return square(r) + r\n"
    ),
    "newmod.py": ("from m import square\n\n\ndef twice(x):\n    return square(x) + square(x)\n"),
}


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


async def _snapshot(store: Store) -> tuple[set, set]:
    nodes = (await store.graph.query(GraphQuery(limit=_ALL))).nodes
    node_set = {
        (n.id, n.kind.value, n.name, n.span, json.dumps(n.attrs, sort_keys=True)) for n in nodes
    }
    edge_set: set = set()
    for n in nodes:
        for e in await store.graph.adjacent(n.id, None, "out"):
            edge_set.add((e.src, e.dst, e.kind.value, e.origin_path))
    return node_set, edge_set


@pytest.fixture
def two_workspaces(tmp_path: Path) -> tuple[Path, Path]:
    # Same leaf dir name so the SymbolID repo slug matches across both.
    a = tmp_path / "wsA" / "proj"
    b = tmp_path / "wsB" / "proj"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    return a, b


async def test_refresh_equals_full_reindex(two_workspaces: tuple[Path, Path]) -> None:
    repo_a, repo_b = two_workspaces

    # A: index S0, mutate to S1, incremental refresh
    _write(repo_a, S0)
    cg_a = await CodeGraph.index(repo_path=repo_a)
    (repo_a / "legacy.py").unlink()
    _write(
        repo_a,
        {
            "m.py": S1["m.py"],
            "conv.py": S1["conv.py"],
            "app.py": S1["app.py"],
            "newmod.py": S1["newmod.py"],
        },
    )
    report = await cg_a.refresh()

    # B: full index of S1 directly
    _write(repo_b, S1)
    cg_b = await CodeGraph.index(repo_path=repo_b, full=True)

    try:
        snap_a = await _snapshot(cg_a.store)
        snap_b = await _snapshot(cg_b.store)
        assert snap_a[0] == snap_b[0], "node sets diverge"
        assert snap_a[1] == snap_b[1], "edge sets diverge"
        # the refresh really did cross-file resolution work
        assert report.resolve.refs_resolved >= 1
    finally:
        await cg_a.close()
        await cg_b.close()


async def test_refresh_noop_when_unchanged(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _write(repo, S0)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        before = await _snapshot(cg.store)
        report = await cg.refresh()  # nothing changed
        after = await _snapshot(cg.store)
        assert before == after
        assert report.files_indexed == 0
        assert report.resolve.refs_resolved == 0
    finally:
        await cg.close()


async def test_delete_only_equivalence(two_workspaces: tuple[Path, Path]) -> None:
    # Deleting an imported file: importer must fall back exactly like a full index.
    repo_a, repo_b = two_workspaces
    _write(repo_a, S0)
    cg_a = await CodeGraph.index(repo_path=repo_a)
    (repo_a / "m.py").unlink()  # app.py now imports a missing module
    await cg_a.refresh()

    _write(
        repo_b,
        {"app.py": S0["app.py"], "conv.py": S0["conv.py"], "legacy.py": S0["legacy.py"]},
    )
    cg_b = await CodeGraph.index(repo_path=repo_b, full=True)
    try:
        assert await _snapshot(cg_a.store) == await _snapshot(cg_b.store)
    finally:
        await cg_a.close()
        await cg_b.close()
