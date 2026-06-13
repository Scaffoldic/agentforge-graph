"""Stage-1 structural pattern heuristics (feat-012) — deterministic, no LLM.

Cheap rules nominate *candidate* patterns for a symbol from its structure (name,
methods, and graph neighbourhood). Recall over precision here: the LLM judge
(stage 2) confirms or rejects each nomination, so a spurious candidate costs one
judge call, while a missed one is never recovered. Framework-free and
golden-tested. Each candidate carries ``evidence`` strings the judge must weigh,
so the verdict cites structure (spec §8).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentforge_graph.core import EdgeKind, GraphStore, Node, NodeKind, SymbolID

# CRUD-ish method names that signal a Repository/DAO.
_CRUD = {
    "get",
    "find",
    "save",
    "add",
    "create",
    "delete",
    "remove",
    "update",
    "list",
    "all",
    "fetch",
    "insert",
    "query",
    "load",
    "store",
}
_FACTORY_VERBS = ("create", "make", "build", "new", "from_", "of")
_OBSERVER_METHODS = {"notify", "subscribe", "unsubscribe", "update", "register", "emit"}


@dataclass
class Candidate:
    """A symbol nominated for one or more patterns, with the structure the judge
    needs (so it doesn't re-query the graph)."""

    symbol_id: str
    name: str
    kind: str
    signature: str
    methods: list[tuple[str, str]]  # (name, signature)
    patterns: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)


def _suffix(name: str, *suffixes: str) -> bool:
    low = name.lower()
    return any(low.endswith(s.lower()) for s in suffixes)


class PatternHeuristics:
    """Nominate candidate patterns for code symbols by structure."""

    async def nominate(self, store: GraphStore, symbol_ids: list[str]) -> list[Candidate]:
        out: list[Candidate] = []
        for sid in symbol_ids:
            node = await store.get(sid)
            if node is None or node.kind not in (NodeKind.CLASS, NodeKind.FUNCTION):
                continue
            methods = await self._methods(store, node.id) if node.kind is NodeKind.CLASS else []
            cand = Candidate(
                symbol_id=node.id,
                name=node.name,
                kind=node.kind.value,
                signature=str(node.attrs.get("signature", "")),
                methods=methods,
            )
            if node.kind is NodeKind.CLASS:
                await self._class_patterns(store, cand)
            else:
                self._function_patterns(cand)
            if cand.patterns:
                out.append(cand)
        return out

    async def _methods(self, store: GraphStore, class_id: str) -> list[tuple[str, str]]:
        methods: list[tuple[str, str]] = []
        for edge in await store.adjacent(class_id, [EdgeKind.CONTAINS], "out"):
            m = await store.get(edge.dst)
            if m is not None and m.kind is NodeKind.METHOD:
                methods.append((m.name, str(m.attrs.get("signature", ""))))
        return methods

    async def _class_patterns(self, store: GraphStore, c: Candidate) -> None:
        names = {m.lower() for m, _ in c.methods}
        crud = sorted(names & _CRUD)

        if _suffix(c.name, "Repository", "Repo", "DAO", "Store"):
            c.patterns.append("Repository")
            c.evidence.append(f"class name ends with a repository suffix ({c.name})")
        elif len(crud) >= 2:
            c.patterns.append("Repository")
            c.evidence.append(f"has CRUD-shaped methods: {', '.join(crud)}")

        if _suffix(c.name, "Service", "UseCase", "Interactor"):
            c.patterns.append("Service")
            c.evidence.append(f"class name ends with a service suffix ({c.name})")

        if _suffix(c.name, "Controller", "Resource", "Handler", "View"):
            c.patterns.append("Controller")
            c.evidence.append(f"class name ends with a controller suffix ({c.name})")

        if _suffix(c.name, "Factory") or any(
            m.lower().startswith(_FACTORY_VERBS) for m, _ in c.methods
        ):
            c.patterns.append("Factory")
            c.evidence.append("name or factory-verb methods (create/make/build/…)")

        if _suffix(c.name, "Builder") or (
            "build" in names
            and any(m.lower().startswith(("with_", "set_", "add_")) for m, _ in c.methods)
        ):
            c.patterns.append("Builder")
            c.evidence.append("a build() method with fluent with_/set_ methods")

        if "get_instance" in names or "instance" in names:
            c.patterns.append("Singleton")
            c.evidence.append("get_instance/instance accessor")

        if names & _OBSERVER_METHODS or _suffix(c.name, "Observer", "Listener", "Subscriber"):
            c.patterns.append("Observer")
            c.evidence.append("observer-shaped methods or name")

        if _suffix(c.name, "Strategy", "Policy"):
            c.patterns.append("Strategy")
            c.evidence.append(f"name ends with a strategy suffix ({c.name})")

        if _suffix(c.name, "Adapter"):
            c.patterns.append("Adapter")
            c.evidence.append(f"name ends with Adapter ({c.name})")
        if _suffix(c.name, "Facade"):
            c.patterns.append("Facade")
            c.evidence.append(f"name ends with Facade ({c.name})")
        if _suffix(c.name, "Decorator"):
            c.patterns.append("Decorator")
            c.evidence.append(f"name ends with Decorator ({c.name})")

        behaviour = [m for m, _ in c.methods if not m.startswith("__")]
        if not behaviour and (c.methods or _suffix(c.name, "DTO", "Dto", "ValueObject", "VO")):
            tag = "DTO" if _suffix(c.name, "DTO", "Dto") else "ValueObject"
            c.patterns.append(tag)
            c.evidence.append("data-only class (no behaviour methods)")

    def _function_patterns(self, c: Candidate) -> None:
        low = c.name.lower()
        if low.startswith(_FACTORY_VERBS) and not low.startswith("__"):
            c.patterns.append("Factory")
            c.evidence.append(f"factory-verb function name ({c.name})")


def class_and_function_ids(nodes: list[Node]) -> list[str]:
    """Symbol ids eligible for pattern tagging (Class/Function), stable order."""
    kinds = {NodeKind.CLASS, NodeKind.FUNCTION}
    return sorted(n.id for n in nodes if n.kind in kinds and SymbolID.parse(n.id).descriptor)
