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
# Receivers that unambiguously denote the enclosing instance/class across the
# packs that capture a receiver: `self` (Py/Rust/Ruby), `this` (TS/JS/Java/C#/
# C++), `$this` (PHP). A call on one of these binds to the enclosing class's
# method (BUG-006); any other receiver is left unresolved (ADR-0004).
_SELF_RECV = frozenset({"self", "this", "$this"})


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


def _path_namespace(path: str) -> str:
    """Rust: the crate-relative module path derived from a file path, in `/` form.
    ``src/a/b.rs`` -> ``a/b``; ``src/a/mod.rs`` -> ``a``; ``src/lib.rs`` /
    ``src/main.rs`` -> ``"" `` (the crate root)."""
    p = path[4:] if path.startswith("src/") else path
    if p.endswith(".rs"):
        p = p[:-3]
    if p.endswith("/mod"):
        p = p[:-4]
    return "" if p in ("lib", "main", "mod") else p


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
        # namespace FQN index (PHP/Java): "App/Foo/Bar" -> (file id, symbol id)
        fqn_to_file: dict[str, str] = {}
        fqn_to_sym: dict[str, str] = {}
        # namespace-prefix index (C#): "App/Geo" -> ({file ids}, {symbol name -> id})
        ns_to_files: dict[str, set[str]] = {}
        ns_to_syms: dict[str, dict[str, str]] = {}
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
            # Sort by id so the name->symbol maps below are deterministic when a
            # file has several same-named callables (e.g. Python @overload stubs):
            # the dict build is last-write-wins and store.neighbors() order is not
            # stable across an incremental vs a full build. Without this, a call
            # resolves to a different (but equally valid) overload instance
            # depending on build history, breaking the incremental == full
            # contract (feat-004).
            members = sorted(
                await store.neighbors(f.id, [EdgeKind.CONTAINS], depth=1),
                key=lambda m: m.id,
            )
            exports.setdefault(module, {}).update({m.name: m.id for m in members})
            # namespace packs: index each top-level symbol by its fully-qualified
            # name (file's declared namespace + symbol name), normalized to "/".
            ns = (
                _path_namespace(ps.path)
                if pack.namespace_from_path
                else f.attrs.get("namespace", "")
            )
            if ns and pack.namespace_sep:
                ns_key = ns.replace(pack.namespace_sep, "/")
                ns_to_files.setdefault(ns_key, set()).add(f.id)
                for m in members:
                    fqn = f"{ns_key}/{m.name}"
                    fqn_to_file.setdefault(fqn, f.id)
                    fqn_to_sym.setdefault(fqn, m.id)
                    ns_to_syms.setdefault(ns_key, {}).setdefault(m.name, m.id)

        stats = ResolveStats()
        new_nodes: list[Node] = []
        edges: list[Edge] = []
        seen_edges: set[tuple[str, str, str]] = set()
        packages: dict[str, str] = {}  # package id -> module
        bindings: dict[str, dict[str, str]] = {}  # file id -> {imported name -> target id}
        # BUG-006: file id -> {local module alias -> in-repo module key}, for
        # whole-module imports (`import m`) and default requires (`const m =
        # require("./m")`). Lets `m.f()` bind to module `m`'s top-level export `f`.
        module_alias: dict[str, dict[str, str]] = {}

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
                # namespace imports (PHP/Java/C#). Path-based handling is skipped.
                if pack is not None and pack.namespace_sep:
                    norm = module.replace(pack.namespace_sep, "/")
                    if pack.namespace_import_prefix:
                        # C#: `using App.Geo` names a namespace -> IMPORTS to every
                        # in-repo file declaring it, and bind all its symbols.
                        tgt_files = ns_to_files.get(norm)
                        if tgt_files:
                            for tf in sorted(tgt_files):
                                if _is_target(ps.path) and _add_edge(f.id, tf, EdgeKind.IMPORTS):
                                    stats.imports_resolved += 1
                            for nm, sym in ns_to_syms.get(norm, {}).items():
                                binding.setdefault(nm, sym)
                        else:
                            pid = _external(ps.lang, ps.repo, module)
                            if _is_target(ps.path) and _add_edge(f.id, pid, EdgeKind.IMPORTS):
                                stats.imports_external += 1
                        continue
                    # Rust: `use crate::a::b::Item` -> strip the crate root prefix
                    # so the path matches a file-derived module key.
                    if pack.namespace_from_path and norm.startswith("crate/"):
                        norm = norm[len("crate/") :]
                    # PHP/Java/Rust: a path naming a single item (class/struct/fn)
                    # -> the file declaring it; bind the item name.
                    tgt_file = fqn_to_file.get(norm)
                    if tgt_file is not None:
                        if _is_target(ps.path) and _add_edge(f.id, tgt_file, EdgeKind.IMPORTS):
                            stats.imports_resolved += 1
                        local_name = module.rsplit(pack.namespace_sep, 1)[-1]
                        binding[local_name] = fqn_to_sym[norm]
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
                    sep = "/" if pack is not None and pack.module_style != "dotted" else "."
                    for nm in names:
                        tgt = exports.get(key, {}).get(nm)
                        if tgt:
                            binding[nm] = tgt
                            continue
                        # `from pkg import sub` where `sub` is an in-repo *submodule*
                        # (not a def of pkg): alias the local name to that module so
                        # `sub.f()` / `extends sub.Base` resolve to its exports, and
                        # point IMPORTS at the submodule file (BUG-006 aliased import).
                        sub_key = f"{key}{sep}{nm}" if key else nm
                        if sub_key in module_to_file:
                            module_alias.setdefault(f.id, {})[nm] = sub_key
                            if _is_target(ps.path) and _add_edge(
                                f.id, module_to_file[sub_key], EdgeKind.IMPORTS
                            ):
                                stats.imports_resolved += 1
                    # CommonJS default require: bind the local name to the target
                    # module's `module.exports = <name>` symbol (BUG-006).
                    if default_name:
                        exp = file_default.get(key, "")
                        tgt = exports.get(key, {}).get(exp) if exp else None
                        if tgt:
                            binding[default_name] = tgt
                        # also a module alias, so `default_name.f()` reaches a
                        # top-level export `f` of the module (BUG-006 member access).
                        module_alias.setdefault(f.id, {})[default_name] = key
                    # whole-module import (`import m`): `m` aliases the module, so
                    # `m.f()` resolves to its top-level export `f` (BUG-006).
                    elif not names:
                        module_alias.setdefault(f.id, {})[module] = key
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
        node_by_id = {n.id: n for n in all_nodes}
        # BUG-006: lazily resolve `self.f()`/`this.f()` to the *enclosing class's*
        # method — a unique, safe match (ADR-0004). Caches keep it cheap and
        # deterministic (methods sorted by id, like the export map above).
        method_cache: dict[str, dict[str, str]] = {}
        enclosing_cache: dict[str, str | None] = {}

        async def _methods_of(class_id: str) -> dict[str, str]:
            cached = method_cache.get(class_id)
            if cached is None:
                members = sorted(
                    await store.neighbors(class_id, [EdgeKind.CONTAINS], depth=1),
                    key=lambda m: m.id,
                )
                cached = {m.name: m.id for m in members}
                method_cache[class_id] = cached
            return cached

        async def _enclosing_class(node_id: str) -> str | None:
            if node_id in enclosing_cache:
                return enclosing_cache[node_id]
            cls: str | None = None
            for e in await store.adjacent(node_id, [EdgeKind.CONTAINS], "in"):
                parent = node_by_id.get(e.src)
                if parent is not None and parent.kind is NodeKind.CLASS:
                    cls = e.src
                    break
            enclosing_cache[node_id] = cls
            return cls

        # --- inheritance -> INHERITS edges (subclass -> base; unique match) ---
        # Resolve bases first and keep a superclass map, so the call loop below can
        # walk it for inherited `self.f()` (the method is defined on a base class).
        superclasses: dict[str, list[str]] = {}
        for n in all_nodes:
            bases = n.attrs.get("bases")
            if not bases or n.kind is not NodeKind.CLASS:
                continue
            owner_file = path_to_file.get(SymbolID.parse(n.id).path)
            local = exports.get(file_module.get(owner_file, ""), {}) if owner_file else {}
            binding = bindings.get(owner_file, {}) if owner_file else {}
            aliases = module_alias.get(owner_file, {}) if owner_file else {}
            resolved: list[str] = []
            for base in bases:
                bt = local.get(base) or binding.get(base)
                # qualified base `mod.Base`: resolve `mod` as an imported module
                # alias, then `Base` as that module's top-level export (BUG-006).
                if bt is None and "." in base:
                    recv, _, base_name = base.rpartition(".")
                    mod_key = aliases.get(recv)
                    if mod_key is not None:
                        bt = exports.get(mod_key, {}).get(base_name)
                # only an in-repo class is a valid base (external/by-name-only stays
                # unresolved — never guessed, ADR-0004)
                tnode = node_by_id.get(bt) if bt else None
                if tnode is not None and tnode.kind is NodeKind.CLASS and bt is not None:
                    resolved.append(bt)
            if not resolved:
                continue
            superclasses[n.id] = resolved
            if _is_target(SymbolID.parse(n.id).path):
                for b in resolved:
                    if _add_edge(n.id, b, EdgeKind.INHERITS):
                        stats.inherits_resolved += 1

        async def _inherited_method(class_id: str, name: str) -> str | None:
            """A method ``name`` defined on a *base* of ``class_id`` — resolved only
            when exactly one base in the transitive closure defines it (no MRO
            guessing across multiple definers, ADR-0004)."""
            seen: set[str] = set()
            found: set[str] = set()
            frontier = list(superclasses.get(class_id, []))
            while frontier:
                b = frontier.pop()
                if b in seen:
                    continue
                seen.add(b)
                m = (await _methods_of(b)).get(name)
                if m:
                    found.add(m)
                frontier.extend(superclasses.get(b, []))
            return next(iter(found)) if len(found) == 1 else None

        # Go: methods are package-scoped and attached to a receiver type, not
        # AST-nested in it. Index them by (package, type) so a call on a method's
        # own receiver (`s.f()`) resolves to a method of that type (BUG-006).
        go_methods: dict[tuple[str, str], dict[str, str]] = {}
        for n in sorted(all_nodes, key=lambda z: z.id):
            rtype = n.attrs.get("recv_type")
            if not rtype:
                continue
            owner = path_to_file.get(SymbolID.parse(n.id).path, "")
            go_methods.setdefault((file_module.get(owner, ""), rtype), {})[n.name] = n.id

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
            aliases = module_alias.get(owner_file, {}) if owner_file else {}
            for ref in refs:
                nm = ref.get("name")
                recv = ref.get("recv")
                target: str | None = None
                if not nm:
                    target = None
                elif recv in _SELF_RECV:
                    # an intra-class call: bind to a method of the enclosing class,
                    # or — failing that — a method inherited from a unique base.
                    cls = await _enclosing_class(n.id)
                    if cls is not None:
                        target = (await _methods_of(cls)).get(nm)
                        if target is None:
                            target = await _inherited_method(cls, nm)
                elif recv is not None and recv == n.attrs.get("recv_var"):
                    # Go: a call on the method's own receiver (`s.f()`) → a method
                    # of the receiver's type.
                    key = (file_module.get(owner_file or "", ""), str(n.attrs.get("recv_type", "")))
                    target = go_methods.get(key, {}).get(nm)
                elif recv is not None:
                    # `m.f()` where `m` is an imported module → its export `f`;
                    # any other receiver is not a unique target (never guessed
                    # onto a same-named module-level def, ADR-0004).
                    mod_key = aliases.get(recv)
                    if mod_key is not None:
                        target = exports.get(mod_key, {}).get(nm)
                else:
                    target = local.get(nm) or binding.get(nm)
                if target and target not in packages:  # external pkg isn't a callable target
                    if _add_edge(n.id, target, EdgeKind.CALLS):
                        stats.refs_resolved += 1
                else:
                    stats.refs_unresolved += 1

        if new_nodes or edges:
            await store.add([*new_nodes, *edges])  # nodes first: edge endpoints must exist
        return stats
