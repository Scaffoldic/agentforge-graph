"""The ``ckg`` command-line interface.

v0.1 ships ``ckg index`` and ``ckg embed``; ``serve-mcp`` and friends land in
feat-008. This layer is framework-free — it drives the deterministic engine
(embedding uses the configured driver: Bedrock by default, ``fake`` for tests).
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

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
    )
    try:
        print(_format_report(cg.stats()))
        if args.embed:
            print(_format_embed(cg.embed_stats()))
    finally:
        await cg.close()
    return 0


async def _embed(args: argparse.Namespace) -> int:
    cg = await CodeGraph.open(repo_path=args.path, config=args.config, languages=args.lang or None)
    try:
        print(_format_embed(await cg.embed()))
    finally:
        await cg.close()
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
    idx.set_defaults(func=_index)

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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code: int = asyncio.run(args.func(args))
    return exit_code
