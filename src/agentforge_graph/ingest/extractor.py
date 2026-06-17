"""``TreeSitterExtractor`` — pass 1 of ingestion (feat-002).

File-isolated: parses one file and emits its ``FileSubgraph`` — definition
nodes (File/Class/Function/Method) with ``CONTAINS`` edges, plus imports and
call sites recorded as node *attrs* (not edges — their targets may live in
other files, which pass 1 may not read). The graph-only resolver (pass 2)
turns those attrs into ``IMPORTS``/``CALLS`` edges.

Parsing uses the standalone ``tree_sitter`` package driven by a grammar from
``tree-sitter-language-pack`` (``Parser(get_language(...))``, never
``get_parser()`` — see the framework note on the ABI split).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from tree_sitter import Language, Parser, Query, QueryCursor
from tree_sitter import Node as TSNode
from tree_sitter_language_pack import get_language

from agentforge_graph.core import (
    Descriptor,
    Edge,
    EdgeKind,
    Extractor,
    FileSubgraph,
    NodeKind,
    Provenance,
    SourceFile,
    SymbolID,
)
from agentforge_graph.core import (
    Node as GraphNode,
)

from .pack import LanguagePack

_CALLABLE = {NodeKind.FUNCTION, NodeKind.METHOD}
_METHOD_OWNERS = {NodeKind.CLASS, NodeKind.INTERFACE}


@cache
def _language(grammar: str) -> Language:
    return get_language(grammar)


@dataclass
class _Def:
    """A captured definition, pre-symbol-id."""

    ts_id: int
    node: TSNode
    kind: NodeKind
    name: str
    enclosing: int | None = None  # ts id of the nearest enclosing def
    symbol_id: str = ""
    bases: list[str] = field(default_factory=list)  # superclass names (INHERITS)
    recv_var: str = ""  # Go: a method's receiver variable name (`s` in `func (s *T)`)
    recv_type: str = ""  # Go: a method's receiver type name (`T`)


def _text(node: TSNode, src: bytes) -> str:
    return src[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def _span(node: TSNode) -> tuple[int, int]:
    return (node.start_point[0] + 1, node.end_point[0] + 1)


def _signature(node: TSNode, src: bytes) -> str:
    """The symbol's first source line (the def/class header), trimmed."""
    text = _text(node, src)
    return text.splitlines()[0].strip() if text else ""


class TreeSitterExtractor(Extractor):
    """Extracts a ``FileSubgraph`` from one source file, in isolation."""

    def __init__(self, pack: LanguagePack, repo: str, commit: str = "") -> None:
        self.pack = pack
        self.repo = repo
        self.commit = commit
        self.name = f"tree-sitter-{pack.language}"
        self._lang = _language(pack.grammar)
        self._parser = Parser(self._lang)
        self._structure_q = Query(self._lang, pack.structure_queries)
        self._reference_q = Query(self._lang, pack.reference_queries)

    def extract(self, file: SourceFile) -> FileSubgraph:
        src = file.text.encode("utf-8")
        root = self._parser.parse(src).root_node
        prov = Provenance.parsed(self.name, self.commit)
        file_id = SymbolID.for_symbol(self.pack.lang_slug, self.repo, file.path, "")

        defs, imports, default_export, namespace = self._structure(root, src)
        self._assign_symbol_ids(defs, file.path)
        by_tsid = {d.ts_id: d for d in defs}
        refs = self._references(root, src, by_tsid, file_id)

        nodes: list[GraphNode] = []
        file_attrs: dict[str, Any] = {}
        if imports:
            file_attrs["imports"] = imports
        if default_export:
            file_attrs["default_export"] = default_export
        if namespace:
            file_attrs["namespace"] = namespace  # PHP/Java/C# package (FQN resolution)
        if file_id in refs:
            file_attrs["refs"] = refs[file_id]
        nodes.append(
            GraphNode(
                id=file_id,
                kind=NodeKind.FILE,
                name=file.path.rsplit("/", 1)[-1],
                provenance=prov,
                attrs=file_attrs,
            )
        )

        edges: list[Edge] = []
        for d in defs:
            attrs: dict[str, Any] = {"signature": _signature(d.node, src)}
            if d.symbol_id in refs:
                attrs["refs"] = refs[d.symbol_id]
            if d.bases:  # INHERITS: superclass names, resolved in pass 2
                attrs["bases"] = d.bases
            if d.recv_var:  # Go: receiver var/type, for receiver self-calls (pass 2)
                attrs["recv_var"] = d.recv_var
                attrs["recv_type"] = d.recv_type
            nodes.append(
                GraphNode(
                    id=d.symbol_id,
                    kind=d.kind,
                    name=d.name,
                    span=_span(d.node),
                    provenance=prov,
                    attrs=attrs,
                )
            )
            parent_id = by_tsid[d.enclosing].symbol_id if d.enclosing in by_tsid else file_id
            edges.append(
                Edge(src=parent_id, dst=d.symbol_id, kind=EdgeKind.CONTAINS, provenance=prov)
            )

        nodes.sort(key=lambda n: (n.span or (0, 0), n.id))
        edges.sort(key=lambda e: (e.src, e.dst, e.kind.value))
        return FileSubgraph(
            path=file.path, content_hash=file.content_hash, nodes=nodes, edges=edges
        )

    # --- structure pass -------------------------------------------------

    def _structure(
        self, root: TSNode, src: bytes
    ) -> tuple[list[_Def], list[dict[str, Any]], str, str]:
        defs: list[_Def] = []
        imports: list[dict[str, Any]] = []
        default_export = ""  # CommonJS `module.exports = <name>` (BUG-006)
        namespace = ""  # PHP/Java/C# package declaration (FQN import resolution)
        class_bases: dict[int, list[str]] = defaultdict(list)  # class node id -> base names
        method_recv: dict[int, tuple[str, str]] = {}  # method node id -> (recv var, recv type)
        rules = self.pack.descriptor_rules
        for _pattern, caps in QueryCursor(self._structure_q).matches(root):
            def_cap = next((c for c in caps if c.startswith("def.")), None)
            if def_cap is not None:
                kind = rules.kind_for(def_cap)
                names = caps.get("name")
                if kind is None or not names:
                    continue
                node = caps[def_cap][0]
                defs.append(_Def(ts_id=node.id, node=node, kind=kind, name=_text(names[0], src)))
            elif "base.name" in caps:
                # a base class of a class definition (INHERITS); one match per base
                cls = caps.get("base.def")
                if cls:
                    class_bases[cls[0].id].extend(_text(b, src) for b in caps["base.name"])
            elif "recv.var" in caps:
                # Go: a method's receiver `(s *T)` — bind the var name + type
                meth, rvar, rtype = caps.get("recv.method"), caps["recv.var"], caps.get("recv.type")
                if meth and rtype:
                    method_recv[meth[0].id] = (_text(rvar[0], src), _text(rtype[0], src))
            elif "import" in caps:
                mods = caps.get("import.module", [])
                dflt = caps.get("import.default")
                imports.append(
                    {
                        "module": _text(mods[0], src) if mods else "",
                        "names": [_text(n, src) for n in caps.get("import.name", [])],
                        # CommonJS default require binding: `const x = require(...)`
                        "default": _text(dflt[0], src) if dflt else "",
                        "line": caps["import"][0].start_point[0] + 1,
                    }
                )
            elif "namespace" in caps:
                ns = caps.get("namespace")
                if ns:
                    namespace = _text(ns[0], src)
            elif "export" in caps:
                ed = caps.get("export.default")
                if ed:
                    default_export = _text(ed[0], src)
        for d in defs:
            if d.ts_id in class_bases:
                d.bases = class_bases[d.ts_id]
            if d.ts_id in method_recv:
                d.recv_var, d.recv_type = method_recv[d.ts_id]
        self._link_scopes(defs)
        return defs, imports, default_export, namespace

    def _link_scopes(self, defs: list[_Def]) -> None:
        idset = {d.ts_id for d in defs}
        by_tsid = {d.ts_id: d for d in defs}
        for d in defs:
            anc = d.node.parent
            while anc is not None and anc.id not in idset:
                anc = anc.parent
            d.enclosing = anc.id if anc is not None else None
            # a function whose nearest enclosing def is a class is a method
            if (
                d.kind is NodeKind.FUNCTION
                and d.enclosing is not None
                and by_tsid[d.enclosing].kind in _METHOD_OWNERS
            ):
                d.kind = NodeKind.METHOD

    def _assign_symbol_ids(self, defs: list[_Def], path: str) -> None:
        by_tsid = {d.ts_id: d for d in defs}
        # overload disambiguator: nth same-named callable in the same scope (source order)
        counter: dict[tuple[int | None, str], int] = defaultdict(int)
        disamb: dict[int, int] = {}
        for d in sorted(defs, key=lambda d: d.node.start_byte):
            if d.kind in _CALLABLE:
                key = (d.enclosing, d.name)
                disamb[d.ts_id] = counter[key]
                counter[key] += 1
        for d in defs:
            chain: list[_Def] = []
            cur: _Def | None = d
            while cur is not None:
                chain.append(cur)
                cur = by_tsid.get(cur.enclosing) if cur.enclosing is not None else None
            chain.reverse()
            descriptor = "".join(self._suffix(x, disamb.get(x.ts_id, 0)) for x in chain)
            d.symbol_id = SymbolID.for_symbol(self.pack.lang_slug, self.repo, path, descriptor)

    @staticmethod
    def _suffix(d: _Def, disambiguator: int) -> str:
        if d.kind in (NodeKind.CLASS, NodeKind.INTERFACE):
            return Descriptor.type(d.name)
        if d.kind in _CALLABLE:
            return Descriptor.method(d.name, disambiguator)
        return Descriptor.term(d.name)

    # --- reference pass -------------------------------------------------

    def _references(
        self, root: TSNode, src: bytes, by_tsid: dict[int, _Def], file_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        idset = set(by_tsid)
        # Keyed by the call node so a bare + receiver-capturing pattern that both
        # match the same call (Java/Ruby, where one node type serves `f()` and
        # `recv.f()`) yield ONE ref — the receiver merged in. Distinct-node-type
        # grammars (Py/TS/JS/C#/Rust/PHP/C++) never collide, so this is a no-op
        # for them; insertion order preserves source order.
        owner_of: dict[int, str] = {}
        ref_of: dict[int, dict[str, Any]] = {}
        for _pattern, caps in QueryCursor(self._reference_q).matches(root):
            if "call" not in caps:
                continue
            callees = caps.get("call.callee")
            if not callees:
                continue
            call_node = caps["call"][0]
            ref = ref_of.get(call_node.id)
            if ref is None:
                anc = call_node.parent
                while anc is not None and anc.id not in idset:
                    anc = anc.parent
                owner_of[call_node.id] = by_tsid[anc.id].symbol_id if anc is not None else file_id
                ref = {"name": _text(callees[0], src), "line": call_node.start_point[0] + 1}
                ref_of[call_node.id] = ref
            # BUG-006: the receiver of an attribute call (`recv.f()`), when the pack
            # captures it — lets the resolver bind `self.f()`/`this.f()` to the
            # enclosing class's method and refuse to guess for other receivers.
            recv = caps.get("call.recv")
            if recv and "recv" not in ref:
                ref["recv"] = _text(recv[0], src)
        refs: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for cid, ref in ref_of.items():
            refs[owner_of[cid]].append(ref)
        return dict(refs)
