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

from agentforge_graph.embed import EmbedReport
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.ingest.report import IndexReport


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
    if report.skipped:
        shown = ", ".join(report.skipped[:5]) + (" …" if len(report.skipped) > 5 else "")
        lines.append(f"  skipped {len(report.skipped)}: {shown}")
    return "\n".join(lines)


def _format_embed(report: EmbedReport) -> str:
    return (
        f"embedded {report.embedded} chunks across {report.files} files "
        f"({report.skipped_unchanged} unchanged) — model {report.model}, dim {report.dim}"
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
    finally:
        await cg.close()
    by_kind: dict[str, int] = {}
    for n in nodes:
        by_kind[n.kind.value] = by_kind.get(n.kind.value, 0) + 1
    lines = [
        f"indexed commit: {meta.indexed_commit or '(none)'}",
        f"head commit:    {head or '(not a git repo)'}",
        f"dirty:          {'yes — run ckg index' if dirty else 'no'}",
        f"files indexed:  {len(meta.files)}",
        f"nodes:          {len(nodes)}"
        + (" (" + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())) + ")" if nodes else ""),
        f"store:          {root}",
    ]
    print("\n".join(lines))
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
    try:
        report = await cg.enrich(budget_usd=args.budget_usd)
        by = ", ".join(f"{k}={v}" for k, v in sorted(report.by_pattern.items()))
        print(
            f"enriched: {report.candidates} candidates, {report.judged} judged, "
            f"{report.tagged} tagged — ${report.cost_usd:.4f}"
            + (" [budget tripped]" if report.budget_tripped else "")
        )
        if by:
            print(f"  patterns: {by}")
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
    from agentforge_graph.serve import serve_mcp

    await serve_mcp(repo_path=args.repo, config=args.config, refresh_on_call=args.refresh_on_call)
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
    cg = await CodeGraph.open(repo_path=args.path, config=args.config)
    try:
        pack = await cg.retrieve(
            query=args.query, symbol=args.symbol, mode=args.mode, k=args.k, depth=args.depth
        )
        rendered = pack.render(args.budget)
        print(rendered if rendered else "(no results)")
    finally:
        await cg.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ckg", description="Code Knowledge Graph engine")
    sub = parser.add_subparsers(dest="command", required=True)

    idx = sub.add_parser("index", help="index a repository into the graph")
    idx.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
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
    idx.set_defaults(func=_index)

    st = sub.add_parser("status", help="show the index commit, staleness and node counts")
    st.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    st.add_argument("--config", default=None, help="path to ckg.yaml")
    st.set_defaults(func=_status)

    emb = sub.add_parser("embed", help="chunk + embed an already-indexed repository")
    emb.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    emb.add_argument("--lang", action="append", help="restrict to a language (repeatable)")
    emb.add_argument("--config", default=None, help="path to ckg.yaml")
    emb.set_defaults(func=_embed)

    qry = sub.add_parser("query", help="retrieve connected context for a question")
    qry.add_argument("query", nargs="?", default=None, help="natural-language query")
    qry.add_argument("--path", default=".", help="repository path (default: .)")
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
    qry.add_argument("--config", default=None, help="path to ckg.yaml")
    qry.set_defaults(func=_query)

    mp = sub.add_parser("map", help="print a budget-aware, centrality-ranked repo map")
    mp.add_argument("--path", default=".", help="repository path (default: .)")
    mp.add_argument("--budget", type=int, default=2000, help="token budget (default: 2000)")
    mp.add_argument(
        "--focus", action="append", help="path or symbol id to focus ranking (repeatable)"
    )
    mp.add_argument("--scope", default=None, help="restrict to a path subtree")
    mp.add_argument("--config", default=None, help="path to ckg.yaml")
    mp.set_defaults(func=_map)

    rt = sub.add_parser("routes", help="list extracted framework routes (method, path → handler)")
    rt.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    rt.add_argument("--config", default=None, help="path to ckg.yaml")
    rt.set_defaults(func=_routes)

    dec = sub.add_parser(
        "decisions", help="list architecture decisions (ADRs) and what they govern"
    )
    dec.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    dec.add_argument("--scope", default=None, help="restrict to decisions governing a path subtree")
    dec.add_argument("--status", default=None, help="filter by status (e.g. accepted)")
    dec.add_argument("--config", default=None, help="path to ckg.yaml")
    dec.set_defaults(func=_decisions)

    enr = sub.add_parser("enrich", help="LLM pattern tagging (budgeted; Bedrock Claude)")
    enr.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    enr.add_argument("--budget-usd", type=float, default=None, help="override the per-run USD cap")
    enr.add_argument("--config", default=None, help="path to ckg.yaml")
    enr.set_defaults(func=_enrich)

    tg = sub.add_parser("tagged", help="list symbols carrying a design-pattern tag")
    tg.add_argument("pattern", help="pattern name, e.g. Repository")
    tg.add_argument("path", nargs="?", default=".", help="repository path (default: .)")
    tg.add_argument("--min-confidence", type=float, default=0.7, help="confidence floor (0.7)")
    tg.add_argument("--config", default=None, help="path to ckg.yaml")
    tg.set_defaults(func=_tagged)

    srv = sub.add_parser("serve-mcp", help="run the MCP stdio server exposing the CKG tools")
    srv.add_argument("--repo", default=".", help="repository path (default: .)")
    srv.add_argument("--config", default=None, help="path to ckg.yaml")
    srv.add_argument(
        "--refresh-on-call",
        action="store_true",
        help="(0.1: no-op) refresh the index on tool calls",
    )
    srv.set_defaults(func=_serve_mcp)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code: int = asyncio.run(args.func(args))
    return exit_code
