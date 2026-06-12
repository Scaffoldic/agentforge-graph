"""The ``ckg`` command-line interface.

v0.1 ships ``ckg index``; ``serve-mcp`` and friends land in feat-008. This
layer is framework-free — indexing drives the deterministic engine only.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence

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


async def _index(args: argparse.Namespace) -> int:
    cg = await CodeGraph.index(
        repo_path=args.path,
        languages=args.lang or None,
        config=args.config,
        include=args.include or None,
        exclude=args.exclude or None,
    )
    try:
        print(_format_report(cg.stats()))
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
    idx.set_defaults(func=_index)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    exit_code: int = asyncio.run(args.func(args))
    return exit_code
