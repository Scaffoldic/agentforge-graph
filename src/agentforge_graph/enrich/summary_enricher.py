"""``SummaryEnricher`` (feat-012) — bottom-up module summaries.

Leaf-first over ``CONTAINS``: each file is summarised from its symbols
(signatures) + imports, then one repo summary is synthesised from the file
summaries. Summaries are ``Summary`` nodes (``SUMMARIZES`` → file / a synthesised
``Repository`` node) with ``llm`` provenance, and are embedded
(``source_type="summary"``) so a concept query can land on one and expand to the
code. Budgeted (``BudgetPolicy``), resumable (``DirtySet("summaries")``), and
idempotent: the ``Summary`` node is MERGE-updated and its (stable) ``SUMMARIZES``
edge is created only when missing, and the vector is replaced by ref.
"""

from __future__ import annotations

from agentforge_core.production.budget import BudgetPolicy
from agentforge_core.production.exceptions import BudgetExceeded

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    Embedded,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)
from agentforge_graph.store import Store

from .report import SummaryReport
from .summarizer import FileContext, Summarizer

_SUMMARY_LANG = "summary"
_REPO_PLACEHOLDER = "<repo>"


def summary_id(repo: str, path: str) -> str:
    return SymbolID.for_symbol(_SUMMARY_LANG, repo, path, "summary.")


def repo_node_id(repo: str) -> str:
    return SymbolID.for_symbol("repo", repo, _REPO_PLACEHOLDER, "repository.")


class SummaryEnricher:
    version = "summaries@1"

    def __init__(
        self,
        repo: str,
        summarizer: Summarizer,
        *,
        embedder: object | None = None,
        max_words: int = 120,
        levels: list[str] | None = None,
        budget_usd: float = 2.0,
        commit: str = "",
    ) -> None:
        self.repo = repo
        self.summarizer = summarizer
        self.embedder = embedder
        self.max_words = max_words
        self.levels = levels or ["file", "repo"]
        self.budget_usd = budget_usd
        self.commit = commit
        self.last_done_ids: list[str] = []

    async def enrich(self, store: Store, file_ids: list[str]) -> SummaryReport:
        report = SummaryReport()
        self.last_done_ids = []
        if "file" not in self.levels:
            return report

        budget = BudgetPolicy(usd=self.budget_usd, max_tokens=10**12, max_iterations=10**12)
        prov = Provenance.llm(self.version, 1.0, self.commit)
        nodes: list[Node] = []
        edges: list[Edge] = []
        to_embed: list[tuple[str, str, str]] = []  # (summary_id, path, text)
        file_summaries: list[tuple[str, str]] = []  # (path, text)
        prev_cost = 0.0

        for fid in file_ids:
            file_node = await store.graph.get(fid)
            if file_node is None or file_node.kind is not NodeKind.FILE:
                continue
            try:
                budget.check()
            except BudgetExceeded:
                report.budget_tripped = True
                break
            ctx = await self._file_context(store, file_node)
            summary = await self.summarizer.summarize_file(ctx, self.max_words)
            prev_cost, delta = self.summarizer.cost_usd, self.summarizer.cost_usd - prev_cost
            budget.commit(delta)
            path = SymbolID.parse(fid).path
            sid = summary_id(self.repo, path)
            nodes.append(self._summary_node(sid, summary.text, "file", summary.model, path, prov))
            edges.append(Edge(src=sid, dst=fid, kind=EdgeKind.SUMMARIZES, provenance=prov))
            to_embed.append((sid, path, summary.text))
            file_summaries.append((path, summary.text))
            self.last_done_ids.append(fid)
            report.files_summarized += 1

        # repo tier (bottom-up from the file summaries) — also budget-gated
        repo_ok = "repo" in self.levels and bool(file_summaries) and not report.budget_tripped
        if repo_ok:
            try:
                budget.check()
            except BudgetExceeded:
                report.budget_tripped = True
                repo_ok = False
        if repo_ok:
            repo_summary = await self.summarizer.summarize_repo(
                self.repo, file_summaries, self.max_words
            )
            budget.commit(self.summarizer.cost_usd - prev_cost)
            rnode = repo_node_id(self.repo)
            nodes.append(Node(id=rnode, kind=NodeKind.REPOSITORY, name=self.repo, provenance=prov))
            rsid = summary_id(self.repo, _REPO_PLACEHOLDER)
            nodes.append(
                self._summary_node(rsid, repo_summary.text, "repo", repo_summary.model, "", prov)
            )
            edges.append(Edge(src=rsid, dst=rnode, kind=EdgeKind.SUMMARIZES, provenance=prov))
            to_embed.append((rsid, "", repo_summary.text))
            report.repo_summarized = True

        report.cost_usd = round(self.summarizer.cost_usd, 6)

        # Idempotent without edge churn: MERGE the summary nodes (this refreshes
        # their text), then create each SUMMARIZES edge only if it's missing. The
        # edge target is stable (a summary always summarizes the same file), so
        # we never delete+recreate it — avoiding a Kuzu forward-rel-scan
        # staleness bug (see docs/framework note).
        if nodes:
            await store.graph.add(list(nodes))
        for edge in edges:
            existing = await store.graph.adjacent(edge.src, [edge.kind], "out")
            if not any(e.dst == edge.dst for e in existing):
                await store.graph.add([edge])
        await self._embed(store, to_embed)
        return report

    # --- helpers ----------------------------------------------------------

    def _summary_node(
        self, sid: str, text: str, level: str, model: str, path: str, prov: Provenance
    ) -> Node:
        return Node(
            id=sid,
            kind=NodeKind.SUMMARY,
            name=f"summary:{path or self.repo}",
            attrs={
                "text": text,
                "level": level,
                "model": model,
                "prompt_version": self.version,
                "path": path,
            },
            provenance=prov,
        )

    async def _file_context(self, store: Store, file_node: Node) -> FileContext:
        symbols: list[tuple[str, str]] = []
        for e in await store.graph.adjacent(file_node.id, [EdgeKind.CONTAINS], "out"):
            child = await store.graph.get(e.dst)
            if child is not None and child.kind in (
                NodeKind.CLASS,
                NodeKind.FUNCTION,
                NodeKind.METHOD,
            ):
                symbols.append((child.name, str(child.attrs.get("signature", ""))))
        imports = [
            str(imp.get("module", ""))
            for imp in file_node.attrs.get("imports", [])
            if imp.get("module")
        ]
        return FileContext(path=SymbolID.parse(file_node.id).path, symbols=symbols, imports=imports)

    async def _embed(self, store: Store, items: list[tuple[str, str, str]]) -> None:
        from agentforge_graph.embed import Embedder

        if not items or not isinstance(self.embedder, Embedder):
            return
        vectors = await self.embedder.embed([text for _, _, text in items], "document")
        embedded = [
            Embedded(
                ref=sid,
                vector=vec,
                kind=NodeKind.SUMMARY,
                attrs={"path": path, "source_type": "summary", "model": self.embedder.name},
            )
            for (sid, path, _text), vec in zip(items, vectors, strict=True)
        ]
        # replace any prior vectors for these refs, then add
        for sid, _path, _text in items:
            await store.vectors.delete_where({"ref": sid})
        await store.vectors.upsert(embedded)
