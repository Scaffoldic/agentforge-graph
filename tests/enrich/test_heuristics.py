"""Stage-1 heuristics golden tests (feat-012): the right patterns are nominated
(recall) and a plain class is not."""

from __future__ import annotations

from agentforge_graph.core import GraphQuery
from agentforge_graph.enrich.heuristics import PatternHeuristics, class_and_function_ids
from agentforge_graph.ingest import CodeGraph


async def _nominations(cg: CodeGraph) -> dict[str, set[str]]:
    nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
    cands = await PatternHeuristics().nominate(cg.store.graph, class_and_function_ids(nodes))
    return {c.name: set(c.patterns) for c in cands}


async def test_structural_nominations(graph: CodeGraph) -> None:
    noms = await _nominations(graph)
    assert "Repository" in noms["OrderRepository"]
    assert "Service" in noms["PaymentService"]
    assert "Factory" in noms["WidgetFactory"]
    assert "Singleton" in noms["ConfigSingleton"]
    assert "Observer" in noms["RequestObserver"]


async def test_plain_class_not_nominated(graph: CodeGraph) -> None:
    noms = await _nominations(graph)
    assert "PlainThing" not in noms  # no pattern signal → no candidate


async def test_crud_methods_nominate_repository(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "p"
    repo.mkdir()
    # no "Repository" suffix, but CRUD-shaped methods
    (repo / "m.py").write_text(
        "class Orders:\n    def find(self, id): ...\n    def save(self, o): ...\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        noms = await _nominations(cg)
        assert "Repository" in noms.get("Orders", set())
    finally:
        await cg.close()


async def test_more_pattern_signals(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "p"
    repo.mkdir()
    (repo / "m.py").write_text(
        "class HttpAdapter:\n    def send(self): ...\n\n\n"
        "class AppFacade:\n    def run(self): ...\n\n\n"
        "class RetryStrategy:\n    def apply(self): ...\n\n\n"
        "class ReportBuilder:\n    def with_title(self, t): ...\n    def build(self): ...\n\n\n"
        "class UserDTO:\n    pass\n\n\n"
        "def make_client():\n    return 1\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        noms = await _nominations(cg)
        assert "Adapter" in noms["HttpAdapter"]
        assert "Facade" in noms["AppFacade"]
        assert "Strategy" in noms["RetryStrategy"]
        assert "Builder" in noms["ReportBuilder"]
        assert "DTO" in noms["UserDTO"]
        assert "Factory" in noms["make_client"]  # factory-verb function
    finally:
        await cg.close()


async def test_controller_by_name(tmp_path) -> None:  # type: ignore[no-untyped-def]
    repo = tmp_path / "api"
    repo.mkdir()
    (repo / "v.py").write_text("class UserController:\n    def show(self): ...\n")
    cg = await CodeGraph.index(repo_path=repo)
    try:
        assert "Controller" in (await _nominations(cg)).get("UserController", set())
    finally:
        await cg.close()


async def test_candidate_carries_evidence_and_methods(graph: CodeGraph) -> None:
    nodes = (await graph.store.graph.query(GraphQuery(limit=10_000))).nodes
    cands = await PatternHeuristics().nominate(graph.store.graph, class_and_function_ids(nodes))
    repo = next(c for c in cands if c.name == "OrderRepository")
    assert repo.evidence  # the judge needs structural evidence to cite
    assert {m for m, _ in repo.methods} >= {"get", "save", "delete", "list"}
