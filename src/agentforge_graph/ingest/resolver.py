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
    def __init__(self, registry: PackRegistry, commit: str = "", go_module: str = "") -> None:
        self.registry = registry
        self.commit = commit
        self.go_module = go_module  # go.mod module path (Go import-prefix stripping)
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
        file_default: dict[str, str] = {}  # module -> CommonJS `module.exports = <name>` (BUG-006)
        # namespace FQN index (PHP/Java/C#): "App/Foo/Bar" -> (file id, symbol id)
        fqn_to_file: dict[str, str] = {}
        fqn_to_sym: dict[str, str] = {}
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
            # Go packages are directory-level: many files share one module key.
            # Keep the first file as the package's IMPORTS target, but *merge*
            # every file's top-level defs into the package's export map so
            # same-package cross-file calls resolve (no import needed in Go).
            # File-level packs (Python/TS/JS) have unique keys, so setdefault +
            # update behave exactly like plain assignment for them.
            module_to_file.setdefault(module, f.id)
            file_module[f.id] = module
            de = f.attrs.get("default_export", "")
            if de:
                file_default[module] = de
            members = await store.neighbors(f.id, [EdgeKind.CONTAINS], depth=1)
            exports.setdefault(module, {}).update({m.name: m.id for m in members})
            # namespace packs: index each top-level symbol by its fully-qualified
            # name (file's declared namespace + symbol name), normalized to "/".
            ns = f.attrs.get("namespace", "")
            if ns and pack.namespace_sep:
                for m in members:
                    fqn = f"{ns}{pack.namespace_sep}{m.name}".replace(pack.namespace_sep, "/")
                    fqn_to_file.setdefault(fqn, f.id)
                    fqn_to_sym.setdefault(fqn, m.id)

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
                # namespace FQN import (PHP/Java/C#): `use App\Foo\Bar` -> resolve
                # to the file declaring Bar (via the FQN index) and bind the class
                # name; not in-repo -> external. Path-based handling is skipped.
                if pack is not None and pack.namespace_sep:
                    fqn = module.replace(pack.namespace_sep, "/")
                    tgt_file = fqn_to_file.get(fqn)
                    if tgt_file is not None:
                        if _is_target(ps.path) and _add_edge(f.id, tgt_file, EdgeKind.IMPORTS):
                            stats.imports_resolved += 1
                        local_name = module.rsplit(pack.namespace_sep, 1)[-1]
                        binding[local_name] = fqn_to_sym[fqn]
                    else:
                        pid = _external(ps.lang, ps.repo, module)
                        if _is_target(ps.path) and _add_edge(f.id, pid, EdgeKind.IMPORTS):
                            stats.imports_external += 1
                        binding.setdefault(module.rsplit(pack.namespace_sep, 1)[-1], pid)
                    continue
                # Resolve the import as written (relative path / dotted module,
                # incl. Python leading-dot relative imports) to a key comparable
                # to the module index. file_module gives the importer's own
                # source-root-stripped module key for relative resolution.
                key = (
                    pack.resolve_import(ps.path, module, file_module.get(f.id, ""))
                    if pack
                    else module
                )
                # directory import: `require("./router")` / `import … "./router"`
                # resolves to `./router/index` (BUG-006 — relative packs).
                if key not in module_to_file and f"{key}/index" in module_to_file:
                    key = f"{key}/index"
                # Go: an import path is `<go.mod module>/<dir>`. If we know the
                # module prefix (from go.mod), strip it exactly — this maps both the
                # *root* package (key "") and any sub-package. Otherwise fall back to
                # suffix-matching leading segments to an in-repo dir. stdlib/third-
                # party never match → stay external.
                if key not in module_to_file and pack is not None and pack.module_style == "go":
                    if self.go_module and (
                        key == self.go_module or key.startswith(self.go_module + "/")
                    ):
                        rel = key[len(self.go_module) :].lstrip("/")
                        if rel in module_to_file:
                            key = rel
                    if key not in module_to_file:
                        segs = key.split("/")
                        for i in range(1, len(segs)):
                            cand = "/".join(segs[i:])
                            if cand in module_to_file:
                                key = cand
                                break
                default_name = imp.get("default", "")
                if key in module_to_file:
                    if _is_target(ps.path) and _add_edge(
                        f.id, module_to_file[key], EdgeKind.IMPORTS
                    ):
                        stats.imports_resolved += 1
                    for nm in names:
                        tgt = exports.get(key, {}).get(nm)
                        if tgt:
                            binding[nm] = tgt
                    # CommonJS default require: bind the local name to the target
                    # module's `module.exports = <name>` symbol (BUG-006).
                    if default_name:
                        exp = file_default.get(key, "")
                        tgt = exports.get(key, {}).get(exp) if exp else None
                        if tgt:
                            binding[default_name] = tgt
                    # wildcard import (Ruby `require_relative`): a name-less in-repo
                    # import makes all the target file's top-level defs callable.
                    if pack is not None and pack.wildcard_import and not names and not default_name:
                        for nm, tgt in exports.get(key, {}).items():
                            binding.setdefault(nm, tgt)
                else:
                    pid = _external(ps.lang, ps.repo, module)
                    if _is_target(ps.path) and _add_edge(f.id, pid, EdgeKind.IMPORTS):
                        stats.imports_external += 1
                    for nm in names:
                        binding.setdefault(nm, pid)
                    if default_name:
                        binding.setdefault(default_name, pid)
                    if not names and not default_name:
                        binding.setdefault(module.split(".")[-1], pid)

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
