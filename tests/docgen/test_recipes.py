"""feat-016 chunk 2: the recipe seam + the architecture recipe over a real index."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.docgen import DocTarget, DocType, get_recipe
from agentforge_graph.docgen.errors import DocDisabled
from agentforge_graph.docgen.recipes import ArchitectureRecipe
from agentforge_graph.ingest import CodeGraph

_SRC = """\
class Repo:
    def save(self):
        return validate()


def validate():
    return True
"""


@pytest.fixture
async def cg(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    (tmp_path / "app.py").write_text(_SRC)
    graph = await CodeGraph.index(repo_path=tmp_path)
    yield graph
    await graph.close()


def test_registry_lookup() -> None:
    recipe = get_recipe(DocType.ARCHITECTURE)
    assert isinstance(recipe, ArchitectureRecipe)


def test_unregistered_doc_type_raises() -> None:
    # DESIGN has no recipe registered until chunk 4.
    with pytest.raises(DocDisabled, match="design"):
        get_recipe(DocType.DESIGN)


async def test_architecture_seed_grounds_on_real_symbols(cg: CodeGraph) -> None:
    pack = await get_recipe(DocType.ARCHITECTURE).seed(cg, DocTarget(type=DocType.ARCHITECTURE))
    assert pack.target.type is DocType.ARCHITECTURE
    assert pack.facts, "expected the seed to carry structural facts"

    names = {f.ref.name for f in pack.facts}
    assert names & {"Repo", "save", "validate"}

    for f in pack.facts:
        assert f.source == "parsed"  # structural facts are >= parsed by construction
        assert f.ref.id  # a real symbol id
        assert f.ref.path == "app.py"


async def test_architecture_seed_has_no_llm_notes_without_enrichment(cg: CodeGraph) -> None:
    # No creds / no enrichment in CI → no repo summary → notes empty (llm framing
    # only appears once summaries exist), and no llm fact leaks into `facts`.
    pack = await get_recipe(DocType.ARCHITECTURE).seed(cg, DocTarget(type=DocType.ARCHITECTURE))
    assert pack.notes == ()
    assert all(f.source != "llm" for f in pack.facts)
