"""Stage-1 structural pattern heuristics (feat-012) — deterministic, no LLM.

Cheap rules nominate *candidate* patterns for a symbol from its structure (name,
methods, and graph neighbourhood). Recall over precision here: the LLM judge
(stage 2) confirms or rejects each nomination, so a spurious candidate costs one
judge call, while a missed one is never recovered. Framework-free and
golden-tested. Each candidate carries ``evidence`` strings the judge must weigh,
so the verdict cites structure (spec §8).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

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

# Role hints keyed by a name/base **suffix** → the pattern it nominates. Applied
# to a class's own name and to its base classes (ENH-001).
_ROLE_SUFFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("Repository", "Repo", "DAO", "Store"), "Repository"),
    (("Service", "UseCase", "Interactor"), "Service"),
    (("Controller", "Resource", "Handler", "View"), "Controller"),
    (("Factory",), "Factory"),
    (("Builder",), "Builder"),
    (("Strategy", "Policy"), "Strategy"),
    (("Adapter",), "Adapter"),
    (("Facade",), "Facade"),
    (("Decorator",), "Decorator"),
    (("Observer", "Listener", "Subscriber"), "Observer"),
)
# Extra name suffixes considered only in `recall="broad"` mode.
_BROAD_SUFFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("Manager", "Provider", "Engine", "Coordinator"), "Service"),
    (("Gateway", "Client", "Wrapper", "Proxy"), "Adapter"),
)
# Base classes that don't imply an implementable role (skip for the Strategy
# "implements an interface" broad signal).
_TRIVIAL_BASES = {
    "object",
    "Exception",
    "BaseException",
    "BaseModel",
    "Enum",
    "StrEnum",
    "IntEnum",
    "Protocol",
    "Generic",
    "ABC",
    "Dict",
    "List",
    "Set",
    "Tuple",
    "NamedTuple",
    "TypedDict",
    "dict",
    "list",
    "set",
    "tuple",
}
_CLASS_BASES_RE = re.compile(r"class\s+\w+\s*\(([^)]*)\)")


def _base_names(signature: str) -> list[str]:
    """Base classes parsed from a class signature line (``class X(A, b.C):`` →
    ``["A", "C"]``). Avoids needing INHERITS edges in the graph (ENH-001)."""
    m = _CLASS_BASES_RE.search(signature)
    if not m:
        return []
    bases: list[str] = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part or "=" in part:  # skip metaclass=… / keyword bases
            continue
        leaf = part.split(".")[-1].split("[")[0].strip()  # abc.ABC→ABC, Generic[T]→Generic
        if leaf[:1].isalpha():
            bases.append(leaf)
    return bases


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


Recall = Literal["conservative", "broad"]


class PatternHeuristics:
    """Nominate candidate patterns for code symbols by structure. ``recall``
    controls breadth: ``conservative`` (default) is name + base-class + shape
    signals; ``broad`` also nominates extra name suffixes and ABC
    implementations (more judge calls, higher recall) — ENH-001."""

    def __init__(self, recall: Recall = "conservative") -> None:
        self.recall = recall

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

    @staticmethod
    def _nominate(c: Candidate, pattern: str, evidence: str) -> None:
        if pattern not in c.patterns:
            c.patterns.append(pattern)
        c.evidence.append(evidence)

    async def _class_patterns(self, store: GraphStore, c: Candidate) -> None:
        names = {m.lower() for m, _ in c.methods}
        crud = sorted(names & _CRUD)
        bases = _base_names(c.signature)

        # --- name-suffix signals ---
        for suffixes, pattern in _ROLE_SUFFIXES:
            if _suffix(c.name, *suffixes):
                self._nominate(c, pattern, f"name ends with a {pattern} suffix ({c.name})")

        # --- base-class signals (subclass of a role-named ABC) — ENH-001 ---
        for base in bases:
            for suffixes, pattern in _ROLE_SUFFIXES:
                if _suffix(base, *suffixes):
                    self._nominate(c, pattern, f"inherits {base} (a {pattern})")

        # --- shape signals ---
        if len(crud) >= (1 if self.recall == "broad" else 2):
            self._nominate(c, "Repository", f"has CRUD-shaped methods: {', '.join(crud)}")
        if any(m.lower().startswith(_FACTORY_VERBS) for m, _ in c.methods):
            self._nominate(c, "Factory", "factory-verb methods (create/make/build/…)")
        if "build" in names and any(
            m.lower().startswith(("with_", "set_", "add_")) for m, _ in c.methods
        ):
            self._nominate(c, "Builder", "a build() method with fluent with_/set_ methods")
        if "get_instance" in names or "instance" in names:
            self._nominate(c, "Singleton", "get_instance/instance accessor")
        if names & _OBSERVER_METHODS:
            self._nominate(c, "Observer", "observer-shaped methods (notify/subscribe/…)")

        behaviour = [m for m, _ in c.methods if not m.startswith("__")]
        if not behaviour and (c.methods or _suffix(c.name, "DTO", "Dto", "ValueObject", "VO")):
            tag = "DTO" if _suffix(c.name, "DTO", "Dto") else "ValueObject"
            self._nominate(c, tag, "data-only class (no behaviour methods)")

        # --- broad mode: extra suffixes + ABC-implementation as Strategy ---
        if self.recall == "broad":
            for suffixes, pattern in _BROAD_SUFFIXES:
                if _suffix(c.name, *suffixes):
                    self._nominate(c, pattern, f"name ends with {pattern}-ish suffix ({c.name})")
            implementable = [b for b in bases if b not in _TRIVIAL_BASES]
            if implementable and behaviour:
                self._nominate(c, "Strategy", f"implements interface(s) {', '.join(implementable)}")

    def _function_patterns(self, c: Candidate) -> None:
        low = c.name.lower()
        if low.startswith(_FACTORY_VERBS) and not low.startswith("__"):
            c.patterns.append("Factory")
            c.evidence.append(f"factory-verb function name ({c.name})")


def class_and_function_ids(nodes: list[Node]) -> list[str]:
    """Symbol ids eligible for pattern tagging (Class/Function), stable order."""
    kinds = {NodeKind.CLASS, NodeKind.FUNCTION}
    return sorted(n.id for n in nodes if n.kind in kinds and SymbolID.parse(n.id).descriptor)
