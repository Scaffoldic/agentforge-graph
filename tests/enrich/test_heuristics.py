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


async def test_base_class_signal_nominates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # ENH-001: a class whose OWN name has no role suffix, but which inherits a
    # role-named base, is still nominated (from the class signature).
    repo = tmp_path / "p"
    repo.mkdir()
    (repo / "m.py").write_text(
        "class VectorStore:\n    def search(self): ...\n\n\n"
        "class Lance(VectorStore):\n    def search(self):\n        return 1\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        noms = await _nominations(cg)
        assert "Repository" in noms["Lance"]  # inherits *Store base
    finally:
        await cg.close()


async def test_recall_broad_adds_signals(tmp_path) -> None:  # type: ignore[no-untyped-def]
    from agentforge_graph.core import GraphQuery
    from agentforge_graph.enrich.heuristics import PatternHeuristics, class_and_function_ids

    repo = tmp_path / "p"
    repo.mkdir()
    (repo / "m.py").write_text(
        "class Base:\n    def run(self): ...\n\n\n"
        "class CacheManager:\n    def get(self): ...\n\n\n"
        "class Worker(Base):\n    def run(self):\n        return 1\n"
    )
    cg = await CodeGraph.index(repo_path=repo)
    try:
        nodes = (await cg.store.graph.query(GraphQuery(limit=10_000))).nodes
        ids = class_and_function_ids(nodes)
        conservative = {
            c.name: set(c.patterns)
            for c in await PatternHeuristics("conservative").nominate(cg.store.graph, ids)
        }
        broad = {
            c.name: set(c.patterns)
            for c in await PatternHeuristics("broad").nominate(cg.store.graph, ids)
        }
        # CacheManager: Service only under broad; Worker: Strategy (implements Base) under broad
        assert "CacheManager" not in conservative
        assert "Service" in broad["CacheManager"]
        assert "Strategy" in broad.get("Worker", set())
    finally:
        await cg.close()


async def test_candidate_carries_evidence_and_methods(graph: CodeGraph) -> None:
    nodes = (await graph.store.graph.query(GraphQuery(limit=10_000))).nodes
    cands = await PatternHeuristics().nominate(graph.store.graph, class_and_function_ids(nodes))
    repo = next(c for c in cands if c.name == "OrderRepository")
    assert repo.evidence  # the judge needs structural evidence to cite
    assert {m for m, _ in repo.methods} >= {"get", "save", "delete", "list"}
