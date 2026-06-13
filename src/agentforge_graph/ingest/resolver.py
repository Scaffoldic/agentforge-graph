"""``ImportResolver`` — pass 2 of ingestion (feat-002).

Graph-only and idempotent: reads the imports/refs that pass 1 recorded as
node attrs and turns them into ``IMPORTS`` and ``CALLS`` edges. Resolution
is conservative — a call edge is created only when the name resolves to
*exactly one* target (a local top-level def or a uniquely imported name);
ambiguous or external-only calls are left unresolved and tallied, never
guessed (ADR-0004). All edges are written with ``source=resolved`` via
``GraphStore.add`` so they survive ``delete_file`` of the code files.
"""

from __future__ import annotations

import posixpath

from agentforge_graph.core import (
    Descriptor,
    Edge,
    EdgeKind,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)

from .pack import PackRegistry
from .report import ResolveStats

_ALL = 10_000_000  # effectively unbounded query for v0.1 graph sizes
_INIT_FILES = ("__init__.py", "__init__.pyi")


def _detect_source_roots(file_paths: list[str]) -> set[str]:
    """Directories that are a prefix of file paths but **not** part of the import
    namespace — e.g. ``src`` in a ``src/``-layout package (BUG-001). A source
    root is the parent of a *top-level* package (a package dir whose own parent
    is not a package). Detected from ``__init__.py`` presence."""
    pkg_dirs = {posixpath.dirname(p) for p in file_paths if posixpath.basename(p) in _INIT_FILES}
    roots = {posixpath.dirname(d) for d in pkg_dirs if posixpath.dirname(d) not in pkg_dirs}
    return {r for r in roots if r}  # "" (repo-root layout) needs no stripping


def _strip_root(path: str, roots: set[str]) -> str:
    for r in sorted(roots, key=len, reverse=True):
        if path.startswith(r + "/"):
            return path[len(r) + 1 :]
    return path


class ImportResolver:
    def __init__(self, registry: PackRegistry, commit: str = "") -> None:
        self.registry = registry
        self.commit = commit
        self.name = "import-resolver"

    async def resolve(
        self, store: GraphStore, changed_files: list[str] | None = None
    ) -> ResolveStats:
        prov = Provenance.resolved(self.name, self.commit)
        all_nodes = (await store.query(GraphQuery(limit=_ALL))).nodes
        files = [n for n in all_nodes if n.kind is NodeKind.FILE]

        # module index + per-module top-level exports (direct CONTAINS children)
        roots = _detect_source_roots([SymbolID.parse(f.id).path for f in files])
        module_to_file: dict[str, str] = {}
        file_module: dict[str, str] = {}
        exports: dict[str, dict[str, str]] = {}
        for f in files:
            ps = SymbolID.parse(f.id)
            pack = self.registry.for_slug(ps.lang)
            if pack is None:
                continue
            # strip a source root (e.g. `src/`) for namespace (dotted) packs so a
            # file's module key matches how it's imported (BUG-001); relative
            # packs (TS/JS) resolve by path and need no stripping.
            key_path = _strip_root(ps.path, roots) if pack.module_style == "dotted" else ps.path
            module = pack.module_path(key_path)
            module_to_file[module] = f.id
            file_module[f.id] = module
            members = await store.neighbors(f.id, [EdgeKind.CONTAINS], depth=1)
            exports[module] = {m.name: m.id for m in members}

        stats = ResolveStats()
        new_nodes: list[Node] = []
        edges: list[Edge] = []
        seen_edges: set[tuple[str, str, str]] = set()
        packages: dict[str, str] = {}  # package id -> module
        bindings: dict[str, dict[str, str]] = {}  # file id -> {imported name -> target id}

        def _add_edge(src: str, dst: str, kind: EdgeKind) -> bool:
            key = (src, dst, kind.value)
            if key in seen_edges:
                return False
            seen_edges.add(key)
            # Own the edge by its source-side file (the import/call site), so a
            # later incremental re-resolve can invalidate exactly these edges
            # via clear_resolved (feat-004). src is a FILE node (IMPORTS) or a
            # symbol in the caller's file (CALLS); both parse to that file path.
            edges.append(
                Edge(
                    src=src,
                    dst=dst,
                    kind=kind,
                    provenance=prov,
                    origin_path=SymbolID.parse(src).path,
                )
            )
            return True

        def _external(slug: str, repo: str, module: str) -> str:
            pid = SymbolID.for_symbol(slug, repo, "<external>", Descriptor.namespace(module))
            if pid not in packages:
                packages[pid] = module
                new_nodes.append(
                    Node(
                        id=pid,
                        kind=NodeKind.PACKAGE,
                        name=module,
                        attrs={"external": True},
                        provenance=prov,
                    )
                )
            return pid

        def _is_target(path: str) -> bool:
            return changed_files is None or path in changed_files

        # --- imports -> IMPORTS edges + per-file name bindings ---
        for f in files:
            ps = SymbolID.parse(f.id)
            pack = self.registry.for_slug(ps.lang)
            binding = bindings.setdefault(f.id, {})
            for imp in f.attrs.get("imports", []):
                module = imp.get("module", "")
                names = imp.get("names", [])
                if not module:
                    continue
                # Resolve the import as written (relative path / dotted module)
                # to a key comparable to the module index.
                key = pack.resolve_import(ps.path, module) if pack else module
                if key in module_to_file:
                    if _is_target(ps.path) and _add_edge(
                        f.id, module_to_file[key], EdgeKind.IMPORTS
                    ):
                        stats.imports_resolved += 1
                    for nm in names:
                        tgt = exports.get(key, {}).get(nm)
                        if tgt:
                            binding[nm] = tgt
                else:
                    pid = _external(ps.lang, ps.repo, module)
                    if _is_target(ps.path) and _add_edge(f.id, pid, EdgeKind.IMPORTS):
                        stats.imports_external += 1
                    for nm in names or [module.split(".")[-1]]:
                        binding.setdefault(nm, pid)

        # --- calls -> CALLS edges (unique match only) ---
        path_to_file = {SymbolID.parse(f.id).path: f.id for f in files}
        for n in all_nodes:
            refs = n.attrs.get("refs")
            if not refs:
                continue
            ps = SymbolID.parse(n.id)
            if not _is_target(ps.path):
                continue
            owner_file = path_to_file.get(ps.path)
            local = exports.get(file_module.get(owner_file, ""), {}) if owner_file else {}
            binding = bindings.get(owner_file, {}) if owner_file else {}
            for ref in refs:
                nm = ref.get("name")
                target = local.get(nm) or binding.get(nm) if nm else None
                if target and target not in packages:  # external pkg isn't a callable target
                    if _add_edge(n.id, target, EdgeKind.CALLS):
                        stats.refs_resolved += 1
                else:
                    stats.refs_unresolved += 1

        if new_nodes or edges:
            await store.add([*new_nodes, *edges])  # nodes first: edge endpoints must exist
        return stats
