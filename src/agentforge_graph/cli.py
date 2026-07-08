"""The ``ckg`` command-line interface: ``index``, ``embed``, ``query``,
``map``, ``serve-mcp``, and ``setup``. The engine commands are framework-free
(embedding uses the configured driver: Bedrock by default, ``fake`` for tests);
``serve-mcp`` and ``setup`` lazily load the framework/MCP layer.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

from agentforge_graph.embed import EmbedReport
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.ingest.report import IndexReport
from agentforge_graph.temporal import parse_history

logger = logging.getLogger(__name__)

# ENH-019: directories/files that mark a repo root for upward discovery — a CKG
# index, engine config, or a git work tree. ``.ckg`` (an actual index) is the
# strongest signal; the others let a not-yet-indexed repo still be located.
_REPO_MARKERS = (".ckg", "agentforge.yaml", "ckg.yaml", ".git")


def _add_repo_arg(parser: argparse.ArgumentParser, *, positional: bool = True) -> None:
    """Attach the standard repo-path argument (ENH-006).

    Convention: a positional ``[path]`` on every subcommand, with ``--path`` /
    ``--repo`` accepted as back-compat aliases. Precedence (resolved in
    :func:`_resolve_repo_path`): positional > ``--path``/``--repo`` > the repo
    root discovered upward from the cwd (ENH-019) > ``.``.

    ``positional=False`` is for subcommands whose positional slot is already
    taken (e.g. ``query`` / ``tagged``'s leading argument); they keep only the
    ``--path`` / ``--repo`` aliases.
    """
    if positional:
        parser.add_argument("path", nargs="?", default=None, help="repository path (default: .)")
    primary = "repository path" + ("" if positional else " (default: .)")
    parser.add_argument("--path", dest="path_alias", default=None, help=primary)
    parser.add_argument(
        "--repo", dest="path_alias", default=None, help="repository path (alias of --path)"
    )


def discover_repo_root(start: Path) -> Path | None:
    """Walk upward from ``start`` to the nearest directory that looks like a repo
    root — one holding a CKG index (``.ckg/``), engine config
    (``agentforge.yaml`` / ``ckg.yaml``), or a git work tree (``.git``).

    Returns the first such directory (nearest wins), or ``None`` if none is found
    up to the filesystem root. This lets a bare ``ckg`` invocation serve the repo
    the caller is *inside*, like ``git`` finds its ``.git`` (ENH-019).
    """
    start = start.resolve()
    for d in (start, *start.parents):
        if any((d / marker).exists() for marker in _REPO_MARKERS):
            return d
    return None


def _resolve_repo_path(args: argparse.Namespace) -> None:
    """Collapse positional ``path`` + ``--path``/``--repo`` alias into ``args.path``.

    Precedence: explicit positional > ``--path`` / ``--repo`` alias > the repo
    root discovered upward from the cwd (ENH-019) > ``.`` (the cwd itself, when
    no repo marker is found). When discovery climbs above the cwd, the resolved
    root is announced on stderr so the chosen repo is never a surprise.
    """
    if not (hasattr(args, "path") or hasattr(args, "path_alias")):
        return
    explicit = getattr(args, "path", None) or getattr(args, "path_alias", None)
    if explicit:
        args.path = explicit
        return
    cwd = Path.cwd()
    discovered = discover_repo_root(cwd)
    if discovered is None:
        args.path = "."
        return
    args.path = str(discovered)
    if discovered != cwd.resolve():
        print(f"ckg: using repo root {discovered} (discovered from {cwd})", file=sys.stderr)


def _is_read_only(args: argparse.Namespace) -> bool:
    """Whether the resolved store is consume-only (ENH-018) — from
    ``store.read_only`` in config or the ``--read-only`` flag / ``$CKG_READ_ONLY``
    (already bridged to the env in :func:`main`)."""
    from agentforge_graph.config import StoreConfig, resolve_config
    from agentforge_graph.store import is_read_only

    return is_read_only(StoreConfig.load(resolve_config(args.config, args.path)))


def _refuse_write_if_read_only(args: argparse.Namespace) -> bool:
    """Print an error and return True when a write verb is run against a
    read-only store; the caller then exits non-zero (ENH-018)."""
    if _is_read_only(args):
        print(
            "ckg: refusing to write — the store is read-only "
            "(store.read_only / --read-only / $CKG_READ_ONLY). "
            "This index is consume-only; build it where it is writable.",
            file=sys.stderr,
        )
        return True
    return False


def _print_problem(p: Any, *, stream: Any = None) -> None:
    """Render one preflight Problem (ENH-026): a marker, the summary, and the
    fix on the next line."""
    out = stream if stream is not None else sys.stderr
    mark = "✗" if p.is_error else "⚠"
    scope = f"[{p.scope}] " if p.scope and p.scope != "repo" else ""
    print(f"{mark} {scope}{p.summary}", file=out)
    if p.fix:
        print(f"  fix: {p.fix}", file=out)


def _preflight_or_exit(
    args: argparse.Namespace, *, embed: bool = False, enrich: bool = False
) -> bool:
    """ENH-026: validate the resolved config for the work this verb will do,
    *before* opening the store. Prints each problem with its fix; returns True
    (caller exits non-zero) when any error is found. Warnings don't block."""
    from agentforge_graph.config import resolve_config
    from agentforge_graph.preflight import preflight

    cfg = resolve_config(args.config, args.path)
    problems = preflight(cfg, scope=str(args.path), embed=embed, enrich=enrich)
    for p in problems:
        _print_problem(p)
    return any(p.is_error for p in problems)


# --- ENH-021: workspace build (one manifest, one command) -------------------


async def _run_member_steps(
    repo: str | Path, config: Any, steps: tuple[str, ...], *, full: bool
) -> str:
    """Run the requested build steps for one repo/member and return a one-line
    summary. ``index`` (re)builds; ``embed``/``enrich`` open the existing graph.
    Honors ENH-023 (embed.enabled) via ``cg.embed()``."""
    parts: list[str] = []
    if "index" in steps:
        cg = await CodeGraph.index(repo_path=repo, config=config, full=full)
    else:
        cg = await CodeGraph.open(repo_path=repo, config=config)
    try:
        if "index" in steps:
            r = cg.stats()
            parts.append(f"index {r.files_indexed} files/{r.nodes} nodes")
        if "embed" in steps:
            e = await cg.embed()
            parts.append("embed disabled" if e.disabled else f"embed {e.embedded} chunks")
        if "enrich" in steps:
            er = await cg.enrich()
            parts.append(f"enrich {er.tagged} tagged")
    finally:
        await cg.close()
    return ", ".join(parts)


def _print_member_report(workspace: str, rows: list[tuple[str, str, str]]) -> None:
    print(f"\nworkspace {workspace}: {len(rows)} member(s)")
    width = max((len(n) for n, _, _ in rows), default=0)
    for name, status, detail in rows:
        print(f"  {name:<{width}}  {status:<7}  {detail}")


async def _workspace_run(args: argparse.Namespace, *, steps: tuple[str, ...], full: bool) -> int:
    """Run ``steps`` for every member of ``args.workspace`` (ENH-021). Preflights
    all members up front (ENH-026) and refuses before any work; otherwise builds
    each member with its resolved config (ENH-022), continuing past a failing
    member and reporting per-member results."""
    from agentforge_graph.config import StoreConfig
    from agentforge_graph.preflight import preflight
    from agentforge_graph.serve.workspace import WorkspaceConfig
    from agentforge_graph.store import is_read_only

    ws = WorkspaceConfig.load(args.workspace)
    want_embed, want_enrich = "embed" in steps, "enrich" in steps

    # ENH-026: validate every member's config up front; report all problems once.
    problems = [
        p
        for m in ws.members
        for p in preflight(
            ws.resolve_member_config(m), scope=m.name, embed=want_embed, enrich=want_enrich
        )
    ]
    for p in problems:
        _print_problem(p)
    if any(p.is_error for p in problems):
        print("\nfix the above before building (see `ckg doctor --workspace`).", file=sys.stderr)
        return 2

    fetch = not getattr(args, "no_fetch", False)  # ENH-024: --no-fetch builds offline
    logger.info("workspace %s: %s %d member(s)", ws.workspace, "+".join(steps), len(ws.members))
    rows: list[tuple[str, str, str]] = []
    failed = False
    for i, m in enumerate(ws.members, 1):
        cfg = ws.resolve_member_config(m)
        if is_read_only(StoreConfig.load(cfg)):  # ENH-018: skip consume-only members
            logger.info("[%d/%d] %s: skipped (read-only)", i, len(ws.members), m.name)
            rows.append((m.name, "skipped", "read-only (consume-only)"))
            continue
        try:
            logger.info("[%d/%d] %s: building", i, len(ws.members), m.name)
            # ENH-024: clone/fetch a git member into its managed checkout first.
            repo = ws.prepare_member(m, fetch=fetch)
            rows.append((m.name, "ok", await _run_member_steps(repo, cfg, steps, full=full)))
        except Exception as exc:  # continue-on-error: one bad member doesn't abort the batch
            logger.warning("[%d/%d] %s: FAILED — %s", i, len(ws.members), m.name, exc)
            failed = True
            rows.append((m.name, "FAILED", str(exc)))
    _print_member_report(ws.workspace, rows)
    return 1 if failed else 0


def _format_report(report: IndexReport) -> str:
    lines = [
        f"indexed {report.files_indexed} files: {report.nodes} nodes, {report.edges} edges",
    ]
    if report.by_node_kind:
        lines.append(
            "  nodes: " + ", ".join(f"{k}={v}" for k, v in sorted(report.by_node_kind.items()))
        )
    if report.by_edge_kind:
        lines.append(
            "  edges: " + ", ".join(f"{k}={v}" for k, v in sorted(report.by_edge_kind.items()))
        )
    r = report.resolve
    lines.append(
        f"  resolve: imports {r.imports_resolved} in-repo + {r.imports_external} external, "
        f"calls {r.refs_resolved} resolved / {r.refs_unresolved} unresolved"
    )
    if (
        report.routes_extracted
        or report.models_extracted
        or report.services_extracted
        or report.framework_unresolved
    ):
        lines.append(
            f"  frameworks: {report.routes_extracted} routes, "
            f"{report.models_extracted} models, "
            f"{report.relations_resolved} relations, "
            f"{report.services_extracted} services "
            f"({report.framework_unresolved} unresolved)"
        )
    if report.decisions_indexed or report.governs_resolved:
        lines.append(
            f"  decisions: {report.decisions_indexed} ADRs, "
            f"{report.governs_resolved} governs ({report.mentions_unresolved} unresolved)"
        )
    if report.docs_indexed or report.commits_indexed:
        extra = f", {report.commits_indexed} commits" if report.commits_indexed else ""
        lines.append(
            f"  docs: {report.docs_indexed} files, {report.describes_resolved} describes{extra}"
        )
    if report.skipped:
        shown = ", ".join(report.skipped[:5]) + (" …" if len(report.skipped) > 5 else "")
        lines.append(f"  skipped {len(report.skipped)}: {shown}")
    return "\n".join(lines)


def _format_embed(report: EmbedReport) -> str:
    if report.disabled:  # ENH-023: embed.enabled is false for this repo
        return "embedding skipped — embed.enabled is false (no vectors built)"
    docs = f" + {report.doc_chunks} doc chunks" if report.doc_chunks else ""
    return (
        f"embedded {report.embedded} chunks across {report.files} files{docs} "
        f"({report.skipped_unchanged} unchanged) — model {report.model}, dim {report.dim}"
    )


def _format_backfill(rep: Any) -> str:
    if not rep.ran:
        return f"backfill: skipped ({rep.reason})"
    back = rep.backfilled_through[:10] if rep.backfilled_through else "?"
    return (
        f"backfill: replayed {rep.commits} commits, +{rep.events_added} events "
        f"(history back to {back})"
    )


async def _index(args: argparse.Namespace) -> int:
    if getattr(args, "workspace", None):  # ENH-021: index every member
        steps = ("index", "embed") if args.embed else ("index",)
        return await _workspace_run(args, steps=steps, full=args.full)
    if _refuse_write_if_read_only(args):
        return 2
    if _preflight_or_exit(args, embed=args.embed):
        return 2
    cg = await CodeGraph.index(
        repo_path=args.path,
        languages=args.lang or None,
        config=args.config,
        include=args.include or None,
        exclude=args.exclude or None,
        embed=args.embed,
        full=args.full,
    )
    try:
        print(_format_report(cg.stats()))
        if args.embed:
            print(_format_embed(cg.embed_stats()))
        history = parse_history(args.history)
        if history != 0:
            print(_format_backfill(await cg.backfill(history)))
    finally:
        await cg.close()
    return 0


async def _status(args: argparse.Namespace) -> int:
    from agentforge_graph.config import StoreConfig, resolve_config
    from agentforge_graph.core import GraphQuery
    from agentforge_graph.ingest.codegraph import _git_commit
    from agentforge_graph.ingest.incremental import IndexMeta
    from agentforge_graph.store import resolve_root

    cfg = resolve_config(args.config, args.path)
    store_cfg = StoreConfig.load(cfg)
    root = resolve_root(args.path, store_cfg)
    meta = IndexMeta.load(root)
    head = _git_commit(args.path)
    dirty = bool(head) and bool(meta.indexed_commit) and head != meta.indexed_commit
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        nodes = (await cg.store.graph.query(GraphQuery(limit=10_000_000))).nodes
        temporal = await cg.temporal_status()
    finally:
        await cg.close()
    by_kind: dict[str, int] = {}
    for n in nodes:
        by_kind[n.kind.value] = by_kind.get(n.kind.value, 0) + 1
    if not temporal["enabled"]:
        temporal_line = "off"
    elif not temporal["has_sidecar"]:
        temporal_line = "on — no sidecar yet (re-index)"
    else:
        back = temporal.get("backfilled_through") or ""
        temporal_line = f"on — {temporal['events']} events" + (
            f", history back to {back[:10]}" if back else ""
        )
    lines = [
        f"indexed commit: {meta.indexed_commit or '(none)'}",
        f"head commit:    {head or '(not a git repo)'}",
        f"dirty:          {'yes — run ckg index' if dirty else 'no'}",
        f"files indexed:  {len(meta.files)}",
        f"nodes:          {len(nodes)}"
        + (" (" + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())) + ")" if nodes else ""),
        f"temporal:       {temporal_line}",
        f"store:          {root}" + (" (central)" if store_cfg.central_root else ""),
    ]
    print("\n".join(lines))
    return 0


def _fmt_ts(ts: int) -> str:
    """Epoch seconds → UTC date, or '—' if unknown."""
    if not ts:
        return "—"
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")


def _short(sha: str) -> str:
    return sha[:10] if sha else "—"


async def _history(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        hist = await cg.history(args.symbol)
    finally:
        await cg.close()
    if hist is None:
        print("(no temporal data — enable `temporal:` in ckg.yaml and re-index)")
        return 0
    authors = ", ".join(f"{a.name} ({a.commits})" for a in hist.authors) or "—"
    print(f"symbol:       {hist.symbol_id}")
    print(f"introduced:   {_fmt_ts(hist.introduced_ts)}  ({_short(hist.introduced)})")
    print(f"last changed: {_fmt_ts(hist.last_changed_ts)}  ({_short(hist.last_changed)})")
    print(f"churn:        {hist.churn_30d} (30d) / {hist.churn_90d} (90d)")
    print(f"authors:      {authors}")
    print(f"events:       {len(hist.events)}")
    for e in hist.events:
        print(f"  {_fmt_ts(e.ts)}  {e.event.value:<8} {_short(e.commit)}")
    return 0


async def _changed_since(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        changes = await cg.changed_since(args.ref, scope=args.scope)
    finally:
        await cg.close()
    if not changes:
        print("(nothing changed since that ref, or no temporal data)")
        return 0
    width = max(len(c.kind) for c in changes)
    for c in changes:
        sym = c.symbol_id.rsplit(" ", 1)[-1]
        print(f"{_fmt_ts(c.ts)}  {c.kind:<{width}}  {sym}")
    return 0


async def _embed(args: argparse.Namespace) -> int:
    if getattr(args, "workspace", None):  # ENH-021: embed every member
        return await _workspace_run(args, steps=("embed",), full=False)
    if _refuse_write_if_read_only(args):
        return 2
    if _preflight_or_exit(args, embed=True):
        return 2
    cg = await CodeGraph.open(repo_path=args.path, config=args.config, languages=args.lang or None)
    try:
        print(_format_embed(await cg.embed()))
    finally:
        await cg.close()
    return 0


async def _routes(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        routes = await cg.routes()
        if not routes:
            print("(no routes found)")
            return 0
        width = max(len(r.method) for r in routes)
        for r in routes:
            handler = r.handler.rsplit(" ", 1)[-1] if r.handler else "?"
            # ENH-011: show the cross-file composed path; annotate the base path
            # when a router prefix was applied so the mount is visible.
            path = r.path_pattern or r.path
            mounted = f"  [base {r.path}]" if r.path_pattern and r.path_pattern != r.path else ""
            print(f"{r.method:<{width}}  {path}  →  {handler}  ({r.file}:{r.line}){mounted}")
    finally:
        await cg.close()
    return 0


async def _service_calls(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        calls = await cg.service_calls()
        if not calls:
            print("(no outbound HTTP client calls found)")
            return 0
        width = max(len(c.method) for c in calls)
        for c in calls:
            print(f"{c.method:<{width}}  {c.path}  ({c.framework}, {c.url})  ({c.file}:{c.line})")
    finally:
        await cg.close()
    return 0


async def _models(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        models = await cg.models()
        if not models:
            print("(no models found)")
            return 0
        for m in models:
            table = f" [{m.table}]" if m.table else ""
            fields = ", ".join(m.fields) if m.fields else "—"
            print(f"{m.name}{table}  ({m.file}:{m.line})")
            print(f"    fields: {fields}")
            if m.relations:
                rels = ", ".join(
                    f"{r['via'] or r['kind']}→{r['to']} ({r['kind']})" for r in m.relations
                )
                print(f"    relations: {rels}")
    finally:
        await cg.close()
    return 0


async def _services(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        services = await cg.services()
        if not services:
            print("(no services found)")
            return 0
        for s in services:
            consumers = ", ".join(c.rsplit(" ", 1)[-1] for c in s.injected_into) or "—"
            print(f"{s.name}  ({s.file}:{s.line})")
            print(f"    injected into: {consumers}")
    finally:
        await cg.close()
    return 0


async def _decisions(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        decisions = await cg.decisions(scope=args.scope, status=args.status)
        if not decisions:
            print("(no decisions found)")
            return 0
        for d in decisions:
            adr = d.adr_id or d.path
            govs = f"  governs {len(d.governs)}" if d.governs else ""
            print(f"{d.status:<10}  {d.date or '—':<10}  {adr}  {d.title}{govs}")
    finally:
        await cg.close()
    return 0


async def _enrich(args: argparse.Namespace) -> int:
    if getattr(args, "workspace", None):  # ENH-021: enrich every member (pattern tags)
        return await _workspace_run(args, steps=("enrich",), full=False)
    if _refuse_write_if_read_only(args):
        return 2
    if _preflight_or_exit(args, enrich=True):
        return 2
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    do_summaries = args.summaries or args.all
    do_decisions = args.decisions or args.all
    # patterns is the default only when no other role was explicitly requested
    do_patterns = args.patterns or args.all or not (args.summaries or args.decisions)
    try:
        if do_patterns:
            r = await cg.enrich(budget_usd=args.budget_usd)
            by = ", ".join(f"{k}={v}" for k, v in sorted(r.by_pattern.items()))
            print(
                f"patterns: {r.candidates} candidates, {r.judged} judged, {r.tagged} tagged "
                f"— ${r.cost_usd:.4f}" + (" [budget tripped]" if r.budget_tripped else "")
            )
            if by:
                print(f"  by pattern: {by}")
        if do_summaries:
            s = await cg.summarize(budget_usd=args.budget_usd)
            print(
                f"summaries: {s.files_summarized} files"
                + (" + repo" if s.repo_summarized else "")
                + f" — ${s.cost_usd:.4f}"
                + (" [budget tripped]" if s.budget_tripped else "")
            )
        if do_decisions:
            g = await cg.infer_governs(budget_usd=args.budget_usd)
            print(
                f"decisions: {g.decisions_considered}/{g.decisions_total} considered, "
                f"{g.governs_inferred} GOVERNS inferred — ${g.cost_usd:.4f}"
                + (" [budget tripped]" if g.budget_tripped else "")
            )
    finally:
        await cg.close()
    return 0


async def _build(args: argparse.Namespace) -> int:
    """ENH-021: the one command — index, then embed (where enabled), then enrich
    (with --enrich), for a whole workspace (--workspace) or a single repo."""
    steps = ("index", "embed") + (("enrich",) if args.enrich else ())
    if getattr(args, "workspace", None):
        return await _workspace_run(args, steps=steps, full=args.full)
    if _refuse_write_if_read_only(args):
        return 2
    if _preflight_or_exit(args, embed=True, enrich=args.enrich):
        return 2
    from agentforge_graph.config import resolve_config

    detail = await _run_member_steps(
        args.path, resolve_config(args.config, args.path), steps, full=args.full
    )
    print(detail)
    return 0


async def _summaries(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        items = await cg.summaries(level=args.level)
        if not items:
            print("(no summaries — run `ckg enrich --summaries`)")
            return 0
        for s in items:
            where = s.path or "<repo>"
            print(f"[{s.level}] {where}\n  {s.text}\n")
    finally:
        await cg.close()
    return 0


async def _tagged(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        hits = await cg.tagged(args.pattern, min_confidence=args.min_confidence)
        if not hits:
            print(f"(no symbols tagged {args.pattern})")
            return 0
        for t in hits:
            sym = t.symbol_id.rsplit(" ", 1)[-1]
            print(f"{t.confidence:.2f}  {sym}  — {t.rationale}")
    finally:
        await cg.close()
    return 0


async def _serve_mcp(args: argparse.Namespace) -> int:
    # lazy import: keeps the engine commands (index/embed/query/map) free of
    # the framework/MCP SDK.
    from typing import cast

    from agentforge_graph.config import ServeConfig
    from agentforge_graph.serve import serve_mcp
    from agentforge_graph.serve.server import Transport

    # CLI flags override; otherwise fall back to the serve: block in ckg.yaml.
    cfg = ServeConfig.load(args.config)
    transport = cast(Transport, args.transport or cfg.transport)
    host = args.host or cfg.host
    port = args.port if args.port is not None else cfg.port
    auth_token = args.auth_token or cfg.http_auth_token  # env fallback in build_mcp_server

    await serve_mcp(
        repo_path=args.path,
        config=args.config,
        transport=transport,
        host=host,
        port=port,
        refresh_on_call=args.refresh_on_call,
        auth_token=auth_token,
        allow_unauthenticated=args.allow_unauthenticated,
        workspace=args.workspace,  # ENH-020: federate over a workspace manifest
    )
    return 0


async def _setup(args: argparse.Namespace) -> int:
    # feat-013: wire the CKG into the user's agent. Framework-layer; lazy import
    # keeps the engine commands free of it.
    from agentforge_graph.config import SetupConfig
    from agentforge_graph.setup import SetupError, run_setup

    cfg = SetupConfig.load(args.config)
    agents = [args.agent] if args.agent else (cfg.agents or None)
    try:
        return await run_setup(
            Path(args.path),
            scope=args.scope or cfg.scope,
            transport=args.transport or cfg.transport,
            host=args.host or "127.0.0.1",
            port=args.port if args.port is not None else 8765,
            token=args.auth_token or "",
            agents=agents,
            hooks=args.hooks or cfg.install_hooks,
            do_print=args.print_only,
            assume_yes=args.yes,
            do_check=not args.no_check,
            undo=args.undo,
            force=args.force,
        )
    except SetupError as exc:
        print(f"setup: {exc}", file=sys.stderr)
        return 2


async def _services_map(args: argparse.Namespace) -> int:
    # ENH-020: the cross-service call graph over a workspace, from the CLI.
    from agentforge_graph.serve.federation import FederatedEngine
    from agentforge_graph.serve.workspace import WorkspaceConfig

    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(args.workspace))
    try:
        m = await fed.service_map()
    finally:
        await fed.close()
    if not m["edges"]:
        print("(no cross-service calls resolved)")
    else:
        width = max(len(e["from_service"]) for e in m["edges"])
        for e in m["edges"]:
            print(
                f"{e['from_service']:>{width}} → {e['to_service']:<10} {e['method']:<5} "
                f"{e['route_path']}  (handler={e['handler'] or '-'}, via={e['via']})"
            )
    if m["unresolved"]:
        print(f"\nunresolved ({len(m['unresolved'])}):")
        for u in m["unresolved"]:
            print(f"  {u['from_service']}  {u['method']} {u['path']}  — {u['reason']}")
    return 0


async def _trace(args: argparse.Namespace) -> int:
    # ENH-020: walk the cross-service graph from a service (downstream/upstream).
    from agentforge_graph.serve.federation import FederatedEngine
    from agentforge_graph.serve.workspace import WorkspaceConfig

    fed = FederatedEngine.from_workspace(WorkspaceConfig.load(args.workspace))
    try:
        try:
            t = await fed.trace(args.service, depth=args.depth, direction=args.direction)
        except ValueError as e:  # unknown service / bad direction
            print(f"ckg: {e}", file=sys.stderr)
            return 2
    finally:
        await fed.close()
    arrow = "←" if args.direction == "upstream" else "→"
    print(f"trace {args.direction} from {t['start']}:")
    for h in t["hops"]:
        print(
            f"  [{h['hop']}] {h['from_service']} {arrow} {h['to_service']}  "
            f"{h['method']} {h['route_path']}"
        )
    print(f"reached: {', '.join(t['reached']) or '(none)'}")
    return 0


async def _map(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        text = await cg.repo_map(
            budget_tokens=args.budget, focus=args.focus or None, scope=args.scope
        )
        print(text if text else "(empty map)")
    finally:
        await cg.close()
    return 0


async def _query(args: argparse.Namespace) -> int:
    # feat-015: --schema and --graph select the structural surface; the
    # natural-language retrieval path (below) is unchanged.
    if args.schema:
        return await _query_schema(args)
    if args.graph is not None:
        return await _query_graph(args)
    if args.limit is not None:
        print("--limit only applies to --graph", file=sys.stderr)
        return 2

    from agentforge_graph.temporal import TemporalError

    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        pack = await cg.retrieve(
            query=args.query,
            symbol=args.symbol,
            mode=args.mode,
            k=args.k,
            depth=args.depth,
            as_of=args.as_of,
        )
        rendered = pack.render(args.budget)
        print(rendered if rendered else "(no results)")
    except TemporalError as exc:
        print(f"as_of unavailable: {exc}")
        return 1
    finally:
        await cg.close()
    return 0


async def _query_schema(args: argparse.Namespace) -> int:
    """feat-015: print the queryable vocabulary (needs no index build)."""
    from agentforge_graph.cli_format import render_table

    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        desc = cg.describe_schema()
    finally:
        await cg.close()
    if args.format == "json":
        import json

        print(json.dumps(desc.to_dict(), indent=2))
        return 0
    print(f"query language v{desc.lang_version}\n")
    print("node kinds: " + ", ".join(desc.node_kinds))
    print("edge kinds: " + ", ".join(desc.edge_kinds) + "\n")
    print(
        render_table(
            ("property", "type", "description"),
            [(p.name, p.type, p.doc) for p in desc.node_properties],
        )
    )
    print("\n" + desc.attrs_note)
    return 0


async def _query_graph(args: argparse.Namespace) -> int:
    """feat-015: run a read-only structural query and render the result."""
    from agentforge_graph.cli_format import render_json, render_table
    from agentforge_graph.config import QueryConfig, resolve_config
    from agentforge_graph.store.query import QueryDisabled, QueryError

    qcfg = QueryConfig.load(resolve_config(args.config, args.path))
    if not qcfg.enabled:
        print("the query surface is disabled (query.enabled=false)", file=sys.stderr)
        return 2
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        rt = await cg.query_graph(args.graph, qcfg.to_settings(args.limit))
    except QueryError as exc:
        print(f"query error: {exc}", file=sys.stderr)
        return 2
    except QueryDisabled as exc:
        print(f"query unavailable: {exc}", file=sys.stderr)
        return 2
    finally:
        await cg.close()

    if args.format == "json":
        print(
            render_json(
                rt.columns, rt.rows, truncated=rt.truncated, stopped_reason=rt.stopped_reason
            )
        )
    else:
        print(render_table(rt.columns, rt.rows))
        if rt.truncated:
            print(f"... result truncated ({rt.stopped_reason})", file=sys.stderr)
    return 0


async def _doctor(args: argparse.Namespace) -> int:
    """ENH-026: validate config readiness without indexing — for one repo or a
    whole workspace, reporting every problem (and its fix) in one pass."""
    from agentforge_graph.preflight import preflight

    if getattr(args, "workspace", None):
        from agentforge_graph.serve.workspace import WorkspaceConfig

        ws = WorkspaceConfig.load(args.workspace)
        scopes = [m.name for m in ws.members]
        problems = [
            p
            for m in ws.members
            for p in preflight(ws.resolve_member_config(m), scope=m.name, embed=True, enrich=True)
        ]
    else:
        from agentforge_graph.config import resolve_config

        scopes = [str(args.path)]
        problems = preflight(
            resolve_config(args.config, args.path), scope=str(args.path), embed=True, enrich=True
        )

    errors = [p for p in problems if p.is_error]
    if not problems:
        print(f"ckg doctor: config OK for {', '.join(scopes)} — drivers + credentials ready.")
        return 0
    for p in problems:
        _print_problem(p, stream=sys.stdout)
    if errors:
        print(f"\n{len(errors)} problem(s) must be fixed before indexing.")
        return 2
    print("\nconfig usable (warnings only).")
    return 0


class _VersionAction(argparse.Action):
    """`ckg --version` with the best-effort install channel (feat-013 / FA-001
    Phase 1). Computed lazily so only `--version` pays the import."""

    def __init__(self, option_strings: Sequence[str], dest: str, **kwargs: Any) -> None:
        super().__init__(option_strings, dest, nargs=0, **kwargs)

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: Any,
        values: Any,
        option_string: str | None = None,
    ) -> None:  # noqa: E501
        from agentforge_graph import __version__
        from agentforge_graph.setup.channel import detect_channel

        print(f"ckg {__version__} ({detect_channel()})")
        parser.exit()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ckg", description="Code Knowledge Graph engine")
    # `ckg --version` / `-V` short-circuits during parsing (before the required
    # subcommand check), so it works without a subcommand.
    parser.add_argument(
        "--version", "-V", action=_VersionAction, help="show version + install channel"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    idx = sub.add_parser("index", help="index a repository into the graph")
    _add_repo_arg(idx)
    idx.add_argument("--lang", action="append", help="restrict to a language (repeatable)")
    idx.add_argument(
        "--include", action="append", help="only index paths matching GLOB (repeatable)"
    )
    idx.add_argument(
        "--exclude", action="append", help="also exclude paths matching GLOB (repeatable)"
    )
    idx.add_argument("--config", default=None, help="path to ckg.yaml")
    idx.add_argument("--embed", action="store_true", help="also chunk + embed after indexing")
    idx.add_argument(
        "--full",
        action="store_true",
        help="force a full rebuild instead of incremental (default: incremental)",
    )
    idx.add_argument(
        "--history",
        default=None,
        metavar="N",
        help="backfill the temporal log from the last N commits (or 'full'); "
        "needs temporal enabled (feat-009)",
    )
    idx.add_argument(
        "--workspace",
        default=None,
        help="index every member of a workspace.yaml (ENH-021); each with its resolved config",
    )
    idx.add_argument(
        "--no-fetch",
        action="store_true",
        help="build git members against the existing checkout, without fetching (ENH-024)",
    )
    idx.set_defaults(func=_index)

    st = sub.add_parser("status", help="show the index commit, staleness and node counts")
    _add_repo_arg(st)
    st.add_argument("--config", default=None, help="path to ckg.yaml")
    st.set_defaults(func=_status)

    hist = sub.add_parser("history", help="show a symbol's git evolution (feat-009 temporal)")
    hist.add_argument("symbol", help="exact symbol id")
    _add_repo_arg(hist, positional=False)
    hist.add_argument("--config", default=None, help="path to ckg.yaml")
    hist.set_defaults(func=_history)

    cs = sub.add_parser(
        "changed-since", help="list symbols changed since a git ref (feat-009 temporal)"
    )
    cs.add_argument("ref", help="git ref/commit (e.g. HEAD~20, a tag, a sha)")
    _add_repo_arg(cs, positional=False)
    cs.add_argument("--scope", default=None, help="restrict to a path glob/prefix")
    cs.add_argument("--config", default=None, help="path to ckg.yaml")
    cs.set_defaults(func=_changed_since)

    emb = sub.add_parser("embed", help="chunk + embed an already-indexed repository")
    _add_repo_arg(emb)
    emb.add_argument("--lang", action="append", help="restrict to a language (repeatable)")
    emb.add_argument("--config", default=None, help="path to ckg.yaml")
    emb.add_argument(
        "--workspace", default=None, help="embed every member of a workspace.yaml (ENH-021)"
    )
    emb.set_defaults(func=_embed)

    bld = sub.add_parser(
        "build",
        help="index + embed (+ enrich) a repo or a whole workspace in one command (ENH-021)",
    )
    _add_repo_arg(bld)
    bld.add_argument("--config", default=None, help="path to ckg.yaml")
    bld.add_argument("--workspace", default=None, help="build every member of a workspace.yaml")
    bld.add_argument("--enrich", action="store_true", help="also run LLM enrichment (pattern tags)")
    bld.add_argument(
        "--full", action="store_true", help="force a full rebuild instead of incremental"
    )
    bld.add_argument(
        "--no-fetch",
        action="store_true",
        help="build git members against the existing checkout, without fetching (ENH-024)",
    )
    bld.set_defaults(func=_build)

    qry = sub.add_parser("query", help="retrieve connected context for a question")
    qry.add_argument("query", nargs="?", default=None, help="natural-language query")
    _add_repo_arg(qry, positional=False)
    qry.add_argument("--symbol", default=None, help="anchor at an exact symbol id")
    qry.add_argument(
        "--mode",
        default="context",
        choices=["context", "impact", "definition", "similar"],
        help="retrieval mode (default: context)",
    )
    qry.add_argument("--k", type=int, default=8, help="vector hits (default: 8)")
    qry.add_argument("--depth", type=int, default=1, help="graph expansion hops (default: 1)")
    qry.add_argument("--budget", type=int, default=4000, help="render token budget (default: 4000)")
    qry.add_argument(
        "--as-of",
        dest="as_of",
        default=None,
        metavar="COMMIT",
        help="reconstruct results as of a git commit (feat-009; needs temporal + backfill)",
    )
    qry.add_argument("--config", default=None, help="path to ckg.yaml")
    # feat-015: read-only structural query surface (Cypher subset).
    qry.add_argument(
        "--graph",
        metavar="CYPHER",
        default=None,
        help="run a read-only structural query (Cypher subset) instead of NL retrieval",
    )
    qry.add_argument(
        "--schema",
        action="store_true",
        help="print the queryable vocabulary (node/edge kinds + properties) and exit",
    )
    qry.add_argument(
        "--format",
        default="table",
        choices=["table", "json"],
        help="output format for --graph/--schema (default: table)",
    )
    qry.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap rows for --graph (clamped to the server max)",
    )
    qry.set_defaults(func=_query)

    mp = sub.add_parser("map", help="print a budget-aware, centrality-ranked repo map")
    _add_repo_arg(mp)
    mp.add_argument("--budget", type=int, default=2000, help="token budget (default: 2000)")
    mp.add_argument(
        "--focus", action="append", help="path or symbol id to focus ranking (repeatable)"
    )
    mp.add_argument("--scope", default=None, help="restrict to a path subtree")
    mp.add_argument("--config", default=None, help="path to ckg.yaml")
    mp.set_defaults(func=_map)

    rt = sub.add_parser("routes", help="list extracted framework routes (method, path → handler)")
    _add_repo_arg(rt)
    rt.add_argument("--config", default=None, help="path to ckg.yaml")
    rt.set_defaults(func=_routes)

    md = sub.add_parser("models", help="list extracted ORM data models (table, fields)")
    _add_repo_arg(md)
    md.add_argument("--config", default=None, help="path to ckg.yaml")
    md.set_defaults(func=_models)

    sc = sub.add_parser(
        "service-calls", help="list outbound HTTP client calls (ENH-020 cross-service)"
    )
    _add_repo_arg(sc)
    sc.add_argument("--config", default=None, help="path to ckg.yaml")
    sc.set_defaults(func=_service_calls)

    sv = sub.add_parser("services", help="list DI-provided services and their injection sites")
    _add_repo_arg(sv)
    sv.add_argument("--config", default=None, help="path to ckg.yaml")
    sv.set_defaults(func=_services)

    dec = sub.add_parser(
        "decisions", help="list architecture decisions (ADRs) and what they govern"
    )
    _add_repo_arg(dec)
    dec.add_argument("--scope", default=None, help="restrict to decisions governing a path subtree")
    dec.add_argument("--status", default=None, help="filter by status (e.g. accepted)")
    dec.add_argument("--config", default=None, help="path to ckg.yaml")
    dec.set_defaults(func=_decisions)

    enr = sub.add_parser("enrich", help="LLM enrichment (pattern tags / summaries; Bedrock Claude)")
    _add_repo_arg(enr)
    enr.add_argument("--patterns", action="store_true", help="run pattern tagging (default)")
    enr.add_argument("--summaries", action="store_true", help="run module summaries")
    enr.add_argument(
        "--decisions", action="store_true", help="infer GOVERNS links for ADRs (feat-010)"
    )
    enr.add_argument("--all", action="store_true", help="run patterns, summaries, and decisions")
    enr.add_argument("--budget-usd", type=float, default=None, help="override the per-run USD cap")
    enr.add_argument("--config", default=None, help="path to ckg.yaml")
    enr.add_argument(
        "--workspace", default=None, help="enrich every member of a workspace.yaml (ENH-021)"
    )
    enr.set_defaults(func=_enrich)

    sm = sub.add_parser("summaries", help="list stored module summaries")
    _add_repo_arg(sm)
    sm.add_argument("--level", default=None, help="filter by level (file|repo)")
    sm.add_argument("--config", default=None, help="path to ckg.yaml")
    sm.set_defaults(func=_summaries)

    tg = sub.add_parser("tagged", help="list symbols carrying a design-pattern tag")
    tg.add_argument("pattern", help="pattern name, e.g. Repository")
    _add_repo_arg(tg)
    tg.add_argument("--min-confidence", type=float, default=0.7, help="confidence floor (0.7)")
    tg.add_argument("--config", default=None, help="path to ckg.yaml")
    tg.set_defaults(func=_tagged)

    srv = sub.add_parser(
        "serve-mcp", help="run the MCP server (stdio or http) exposing the CKG tools"
    )
    _add_repo_arg(srv)
    srv.add_argument("--config", default=None, help="path to ckg.yaml")
    srv.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help="MCP transport (default: stdio, or serve.transport in ckg.yaml)",
    )
    srv.add_argument(
        "--workspace",
        default=None,
        help="ENH-020: serve a workspace.yaml of members from one federated endpoint "
        "(survey tools fan across all; pinpoint tools take a `service`)",
    )
    srv.add_argument("--host", default=None, help="http transport bind host (default: 127.0.0.1)")
    srv.add_argument("--port", type=int, default=None, help="http transport port (default: 8765)")
    srv.add_argument(
        "--auth-token",
        default="",
        help="http: require this bearer token (ENH-005; or $CKG_HTTP_AUTH_TOKEN / ckg.yaml)",
    )
    srv.add_argument(
        "--allow-unauthenticated",
        action="store_true",
        help="http: permit binding a non-loopback host with no auth (deliberate opt-in)",
    )
    srv.add_argument(
        "--refresh-on-call",
        action="store_true",
        help="(0.1: no-op) refresh the index on tool calls",
    )
    srv.set_defaults(func=_serve_mcp)

    setup_p = sub.add_parser(
        "setup", help="wire the CKG into your coding agent's MCP config (feat-013)"
    )
    _add_repo_arg(setup_p)
    setup_p.add_argument("--config", default=None, help="path to ckg.yaml")
    setup_p.add_argument(
        "--scope",
        choices=["project", "user"],
        default=None,
        help="project = repo-root .mcp.json (default; shareable); user = ~/.claude.json",
    )
    setup_p.add_argument(
        "--agent", default=None, help="target one agent by key (e.g. claude_code); default: all"
    )
    setup_p.add_argument(
        "--transport",
        choices=["stdio", "http"],
        default=None,
        help="MCP transport to write (default: stdio)",
    )
    setup_p.add_argument(
        "--host", default=None, help="http transport bind host (default: 127.0.0.1)"
    )
    setup_p.add_argument(
        "--port", type=int, default=None, help="http transport port (default: 8765)"
    )
    setup_p.add_argument(
        "--auth-token", default="", help="http: token to embed (ENH-005 bind-safety)"
    )
    setup_p.add_argument(
        "--hooks",
        action="store_true",
        help="also append a managed nudge block to AGENTS.md/CLAUDE.md",
    )
    setup_p.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="dry-run: print the plan, write nothing",
    )
    setup_p.add_argument(
        "--yes", action="store_true", help="apply without the confirm prompt (scripts/CI)"
    )
    setup_p.add_argument(
        "--no-check", action="store_true", help="skip the post-write connection check"
    )
    setup_p.add_argument(
        "--undo", action="store_true", help="remove the MCP entries this tool wrote"
    )
    setup_p.add_argument(
        "--force", action="store_true", help="overwrite an existing 'ckg' entry you authored"
    )
    setup_p.set_defaults(func=_setup)

    wt = sub.add_parser(
        "watch",
        help="watch the repo and re-index on a trigger (feat-014; local store only)",
    )
    _add_repo_arg(wt)
    wt.add_argument("--config", default=None, help="path to ckg.yaml")
    wt.add_argument(
        "--trigger",
        choices=["on-commit", "on-idle", "on-save", "interval", "manual"],
        default=None,
        help="on-commit (default) | on-idle | on-save | interval | manual",
    )
    wt.add_argument(
        "--idle-ms", dest="idle_ms", type=int, default=None, help="on-idle: quiet period (ms)"
    )
    wt.add_argument(
        "--debounce-ms",
        dest="debounce_ms",
        type=int,
        default=None,
        help="on-save: burst-coalesce window (ms)",
    )
    wt.add_argument(
        "--interval-ms",
        dest="interval_ms",
        type=int,
        default=None,
        help="interval: periodic refresh window (ms)",
    )
    wt.add_argument(
        "--embed",
        action="store_true",
        help="also drain embeddings on each refresh (default: structural only)",
    )
    wt.add_argument("--once", action="store_true", help="run one refresh if dirty, then exit")
    wt.add_argument("--status", action="store_true", help="print trigger/store/freshness and exit")
    wt.set_defaults(func=_watch)

    ci_p = sub.add_parser("ci", help="scaffold CI to keep a central index fresh (feat-014)")
    ci_sub = ci_p.add_subparsers(dest="ci_cmd", required=True)
    ci_init = ci_sub.add_parser("init", help="write .github/workflows/ckg-index.yml")
    _add_repo_arg(ci_init)
    ci_init.add_argument("--provider", choices=["github"], default="github", help="CI provider")
    ci_init.add_argument(
        "--mode",
        choices=["incremental", "full"],
        default="incremental",
        help="incremental (default; diff-only) | full",
    )
    ci_init.add_argument("--no-embed", action="store_true", help="omit the ckg embed step")
    ci_init.add_argument("--enrich", action="store_true", help="add an LLM enrichment step")
    ci_init.add_argument(
        "--extra",
        action="append",
        default=[],
        help="PyPI extra to install (repeatable), e.g. --extra bedrock",
    )
    ci_init.add_argument(
        "--force", action="store_true", help="overwrite an unmanaged workflow file"
    )
    ci_init.add_argument(
        "--print",
        dest="print_only",
        action="store_true",
        help="print the workflow, write nothing",
    )
    ci_init.set_defaults(func=_ci_init)

    smap = sub.add_parser(
        "services-map", help="cross-service call graph over a workspace (ENH-020)"
    )
    smap.add_argument("--workspace", required=True, help="path to workspace.yaml")
    smap.set_defaults(func=_services_map)

    tr = sub.add_parser("trace", help="trace a request across services in a workspace (ENH-020)")
    tr.add_argument("service", help="the workspace member to trace from")
    tr.add_argument("--workspace", required=True, help="path to workspace.yaml")
    tr.add_argument(
        "--direction",
        choices=["downstream", "upstream"],
        default="downstream",
        help="downstream (what it calls — data flow) | upstream (who calls it — blast radius)",
    )
    tr.add_argument("--depth", type=int, default=10, help="max hops (default: 10)")
    tr.set_defaults(func=_trace)

    doc = sub.add_parser(
        "doctor", help="validate config readiness (drivers installed, creds present) — ENH-026"
    )
    _add_repo_arg(doc)
    doc.add_argument("--config", default=None, help="path to ckg.yaml")
    doc.add_argument(
        "--workspace", default=None, help="validate every member of a workspace.yaml at once"
    )
    doc.set_defaults(func=_doctor)

    # ENH-018: every subcommand accepts --read-only (assert consume-only for this
    # invocation; write verbs then refuse). The durable form is store.read_only.
    # Logging: every subcommand accepts --log-level / --debug / -v to trace a run
    # (also via $CKG_LOG_LEVEL or logging.level in ckg.yaml).
    for p in sub.choices.values():
        p.add_argument(
            "--read-only",
            action="store_true",
            help="treat the index as consume-only (write verbs refuse); "
            "also via store.read_only / $CKG_READ_ONLY",
        )
        p.add_argument(
            "--log-level",
            default=None,
            choices=["debug", "info", "warning", "error"],
            help="log verbosity (also $CKG_LOG_LEVEL / logging.level in ckg.yaml)",
        )
        p.add_argument("--debug", action="store_true", help="shorthand for --log-level debug")
        p.add_argument(
            "-v", "--verbose", action="store_true", help="shorthand for --log-level info"
        )
    return parser


async def _watch(args: argparse.Namespace) -> int:
    """feat-014: watch the repo and re-run the incremental refresh on a trigger.
    Local embedded store only — refuses a central / read-only store."""
    from agentforge_graph.config import StoreConfig, WatchConfig, resolve_config
    from agentforge_graph.ingest.watch import (
        WatchGuardError,
        WatchSettings,
        ensure_watchable,
        run_once,
        run_watch,
    )
    from agentforge_graph.ingest.watch import status as watch_status
    from agentforge_graph.ingest.watch.source import WatchDependencyError

    cfg = resolve_config(args.config, args.path)
    wcfg = WatchConfig.load(cfg)
    try:
        settings = WatchSettings(
            trigger=args.trigger or wcfg.trigger,
            debounce_ms=args.debounce_ms or wcfg.debounce_ms,
            idle_ms=args.idle_ms or wcfg.idle_ms,
            interval_ms=args.interval_ms or wcfg.interval_ms,
        )
    except ValueError as exc:
        print(f"ckg watch: {exc}", file=sys.stderr)
        return 2

    if args.status:
        print(watch_status(args.path, args.config, settings).render())
        return 0

    # Load-bearing guardrail: watch may only write a local, writable, embedded
    # index. Central / read-only stores are CI's job (ckg ci init).
    try:
        ensure_watchable(StoreConfig.load(cfg), _is_read_only(args))
    except WatchGuardError as exc:
        print(f"ckg watch: {exc}", file=sys.stderr)
        return 2

    embed_on = args.embed or wcfg.embed_on_watch
    if args.once:
        report = await run_once(args.path, args.config, embed=embed_on, enrich=wcfg.enrich_on_watch)
        print(_format_report(cast(IndexReport, report)))
        return 0

    def on_refresh(report: object) -> None:
        print(_format_report(cast(IndexReport, report)))

    def on_gate(active: bool, branch: str) -> None:
        if active:
            print(
                f"ckg watch: watching (trigger={settings.trigger}, "
                f"branch={branch or 'detached'}) — Ctrl-C to stop",
                file=sys.stderr,
            )
        else:
            print(
                f"ckg watch: branch {branch!r} is gated out by watch.branches; "
                "idle until you switch to a watched branch",
                file=sys.stderr,
            )

    try:
        await run_watch(
            args.path,
            args.config,
            settings,
            include=wcfg.branches.include,
            exclude=wcfg.branches.exclude,
            extra_ignore=wcfg.ignore,
            embed_on_watch=embed_on,
            enrich_on_watch=wcfg.enrich_on_watch,
            on_refresh=on_refresh,
            on_gate=on_gate,
        )
    except WatchDependencyError as exc:
        print(f"ckg watch: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nckg watch: stopped", file=sys.stderr)
    return 0


async def _ci_init(args: argparse.Namespace) -> int:
    """feat-014: scaffold a CI workflow that keeps the central index fresh."""
    from agentforge_graph.ci import CiInitError, scaffold_workflow

    try:
        res = scaffold_workflow(
            args.path,
            provider=args.provider,
            mode=args.mode,
            embed=not args.no_embed,
            enrich=args.enrich,
            extras=args.extra or None,
            force=args.force,
            print_only=args.print_only,
        )
    except (CiInitError, ValueError) as exc:
        print(f"ckg ci init: {exc}", file=sys.stderr)
        return 2

    if res.action == "printed":
        print(res.content, end="")
        return 0
    print(f"ckg ci init: {res.action} {res.path}")
    if res.action in ("created", "updated", "overwritten"):
        print(
            "  next: commit this workflow, set the CKG_CENTRAL_STORE_URL secret + "
            "provider creds,\n"
            "        and set store.central_root in agentforge.yaml so CI writes the "
            "central index."
        )
    return 0


def _configure_logging(args: argparse.Namespace) -> None:
    """Set engine log verbosity from flags → $CKG_LOG_LEVEL → ckg.yaml → warning."""
    from agentforge_graph.config import LoggingConfig, resolve_config
    from agentforge_graph.observability import configure, resolve_level

    config_level: str | None = None
    try:
        cfg = resolve_config(getattr(args, "config", None), getattr(args, "path", "."))
        config_level = LoggingConfig.load(cfg).level
    except Exception:  # config problems surface later in the verb, not here
        config_level = None
    configure(
        resolve_level(
            cli_level=getattr(args, "log_level", None),
            cli_debug=getattr(args, "debug", False),
            cli_verbose=getattr(args, "verbose", False),
            config_level=config_level,
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _resolve_repo_path(args)
    _configure_logging(args)
    # ENH-018: bridge --read-only to the env so the store layer (which never sees
    # argparse) honors it uniformly alongside store.read_only.
    if getattr(args, "read_only", False):
        os.environ["CKG_READ_ONLY"] = "1"
    exit_code: int = asyncio.run(args.func(args))
    return exit_code
