"""The ``ckg`` command-line interface: ``index``, ``embed``, ``query``,
``map``, and ``serve-mcp``. The engine commands are framework-free (embedding
uses the configured driver: Bedrock by default, ``fake`` for tests);
``serve-mcp`` lazily loads the framework/MCP layer.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agentforge_graph.embed import EmbedReport
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.ingest.report import IndexReport
from agentforge_graph.temporal import parse_history


def _add_repo_arg(parser: argparse.ArgumentParser, *, positional: bool = True) -> None:
    """Attach the standard repo-path argument (ENH-006).

    Convention: a positional ``[path]`` defaulting to ``.`` on every subcommand,
    with ``--path`` / ``--repo`` accepted as back-compat aliases. Precedence
    (resolved in :func:`main`): positional > ``--path``/``--repo`` > ``.``.

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


def _resolve_repo_path(args: argparse.Namespace) -> None:
    """Collapse positional ``path`` + ``--path``/``--repo`` alias into ``args.path``."""
    if hasattr(args, "path") or hasattr(args, "path_alias"):
        args.path = getattr(args, "path", None) or getattr(args, "path_alias", None) or "."


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
    if report.routes_extracted or report.framework_unresolved:
        lines.append(
            f"  frameworks: {report.routes_extracted} routes "
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
    from agentforge_graph.config import StoreConfig
    from agentforge_graph.core import GraphQuery
    from agentforge_graph.ingest.codegraph import _git_commit
    from agentforge_graph.ingest.incremental import IndexMeta

    root = Path(args.path) / StoreConfig.load(args.config).path
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
        f"store:          {root}",
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
            print(f"{r.method:<{width}}  {r.path}  →  {handler}  ({r.file}:{r.line})")
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
    )
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ckg", description="Code Knowledge Graph engine")
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
    emb.set_defaults(func=_embed)

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _resolve_repo_path(args)
    exit_code: int = asyncio.run(args.func(args))
    return exit_code
