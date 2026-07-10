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


def test_all_four_types_registered() -> None:
    from agentforge_graph.docgen.recipes import RECIPES

    assert set(RECIPES) == set(DocType)  # architecture + ai-context + component + design


def test_unregistered_doc_type_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from agentforge_graph.docgen.recipes import RECIPES

    monkeypatch.delitem(RECIPES, DocType.DESIGN)
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


async def test_ai_context_seed_grounds_on_central_symbols(cg: CodeGraph) -> None:
    pack = await get_recipe(DocType.AI_CONTEXT).seed(cg, DocTarget(type=DocType.AI_CONTEXT))
    assert pack.facts
    assert {f.ref.name for f in pack.facts} & {"Repo", "save", "validate"}
    assert all(f.source != "llm" for f in pack.facts)


async def test_component_seed_scoped_to_path(cg: CodeGraph) -> None:
    pack = await get_recipe(DocType.COMPONENT).seed(
        cg, DocTarget(type=DocType.COMPONENT, scope="app.py")
    )
    assert pack.facts
    assert all(f.ref.path == "app.py" for f in pack.facts)
    assert {f.ref.name for f in pack.facts} >= {"Repo", "validate"}


async def test_component_seed_empty_for_unknown_scope(cg: CodeGraph) -> None:
    pack = await get_recipe(DocType.COMPONENT).seed(
        cg, DocTarget(type=DocType.COMPONENT, scope="nonexistent/")
    )
    assert pack.facts == ()


async def test_design_seed_grounds_on_scope(cg: CodeGraph) -> None:
    pack = await get_recipe(DocType.DESIGN).seed(cg, DocTarget(type=DocType.DESIGN, scope="app.py"))
    assert pack.facts
    assert all(f.source in {"parsed", "resolved"} for f in pack.facts)
