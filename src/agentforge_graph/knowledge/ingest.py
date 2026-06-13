"""``KnowledgeIngestor`` — turn ADR markdown into graph facts (feat-010 MVP).

Each ADR becomes its own ``FileSubgraph`` keyed by its path: a ``Decision``
node, body ``DocChunk`` nodes (``CONTAINS``-linked; not embedded at MVP),
``GOVERNS`` edges to the code it unambiguously mentions, and a ``SUPERSEDES``
edge to the ADR it replaces. Upserting per ADR means edits/deletes ride the
store's per-file machinery (feat-004) with no ChangeDetector change. Runs after
code indexing so the mention indices see current code; re-runs each index, and
GCs decisions whose ADR file is gone.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from agentforge_graph.core import (
    Edge,
    EdgeKind,
    FileSubgraph,
    GraphQuery,
    GraphStore,
    Node,
    NodeKind,
    Provenance,
    SymbolID,
)
from agentforge_graph.core.symbols import normalize_path

from .adr import ADRParser
from .mentions import extract_mentions, resolve_mentions
from .report import KnowledgeStats

_ALL = 10_000_000
_DOC_LANG = "doc"  # SymbolID lang slug — keeps decision ids in their own namespace
_SYMBOL_KINDS = {NodeKind.CLASS, NodeKind.FUNCTION, NodeKind.METHOD}
_NUM_RE = re.compile(r"(\d+)")


class KnowledgeIngestor:
    def __init__(self, repo: str, commit: str = "") -> None:
        self.repo = repo
        self.commit = commit
        self.parser = ADRParser()

    async def ingest(
        self,
        store: GraphStore,
        repo_path: str | Path,
        adr_globs: list[str],
        code_exts: set[str],
    ) -> KnowledgeStats:
        root = Path(repo_path)
        files = self._discover(root, adr_globs)
        current_paths = {rel for rel, _ in files}

        # GC decisions whose ADR file vanished
        for path in await self._existing_decision_paths(store):
            if path not in current_paths:
                await store.delete_file(path)

        if not files:
            return KnowledgeStats()

        path_index, name_index = await self._code_indices(store)
        num_to_decision = {self._adr_num(rel): self._decision_id(rel) for rel, _ in files}

        prov = Provenance.parsed(self.parser.name, self.commit)
        stats = KnowledgeStats()
        built: list[tuple[FileSubgraph, bool]] = []
        for rel, text in files:
            sg, has_supersedes, resolved, unresolved = self._build(
                rel, text, prov, path_index, name_index, num_to_decision, code_exts
            )
            built.append((sg, has_supersedes))
            stats.decisions_indexed += 1
            stats.governs_resolved += resolved
            stats.mentions_unresolved += unresolved

        # round A: land every Decision/DocChunk/GOVERNS (no SUPERSEDES yet)
        for sg, _ in built:
            await store.upsert(self._without(sg, EdgeKind.SUPERSEDES))
        # round B: re-upsert ADRs that supersede, now that all Decisions exist
        for sg, has_supersedes in built:
            if has_supersedes:
                await store.upsert(sg)
        return stats

    # --- discovery & indices ---------------------------------------------

    @staticmethod
    def _discover(root: Path, adr_globs: list[str]) -> list[tuple[str, str]]:
        seen: dict[str, str] = {}
        for pattern in adr_globs:
            for path in sorted(root.glob(pattern)):
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                if rel not in seen:
                    seen[rel] = path.read_text(encoding="utf-8", errors="replace")
        return sorted(seen.items())

    async def _existing_decision_paths(self, store: GraphStore) -> set[str]:
        nodes = (await store.query(GraphQuery(kinds=[NodeKind.DECISION], limit=_ALL))).nodes
        return {SymbolID.parse(n.id).path for n in nodes}

    async def _code_indices(self, store: GraphStore) -> tuple[dict[str, str], dict[str, list[str]]]:
        path_index: dict[str, str] = {}
        name_index: dict[str, list[str]] = {}
        for n in (await store.query(GraphQuery(limit=_ALL))).nodes:
            if n.kind is NodeKind.FILE:
                path_index[SymbolID.parse(n.id).path] = n.id
            elif n.kind in _SYMBOL_KINDS:
                name_index.setdefault(n.name, []).append(n.id)
        return path_index, name_index

    # --- building one ADR subgraph ---------------------------------------

    def _decision_id(self, rel: str) -> str:
        return SymbolID.for_symbol(_DOC_LANG, self.repo, rel, "decision.")

    @staticmethod
    def _adr_num(rel: str) -> str:
        m = _NUM_RE.search(Path(rel).stem)
        return str(int(m.group(1))) if m else ""

    def _build(
        self,
        rel: str,
        text: str,
        prov: Provenance,
        path_index: dict[str, str],
        name_index: dict[str, list[str]],
        num_to_decision: dict[str, str],
        code_exts: set[str],
    ) -> tuple[FileSubgraph, bool, int, int]:
        adr = self.parser.parse(rel, text)
        decision_id = self._decision_id(rel)
        nodes: list[Node] = [
            Node(
                id=decision_id,
                kind=NodeKind.DECISION,
                name=adr.title,
                attrs={
                    "title": adr.title,
                    "status": adr.status,
                    "date": adr.date,
                    "adr_id": adr.adr_id,
                    "path": normalize_path(rel),
                    "well_formed": adr.well_formed,
                },
                provenance=prov,
            )
        ]
        edges: list[Edge] = []
        for i, section in enumerate(adr.sections):
            chunk_id = SymbolID.for_symbol(_DOC_LANG, self.repo, rel, f"docchunk({i}).")
            nodes.append(
                Node(
                    id=chunk_id,
                    kind=NodeKind.DOC_CHUNK,
                    name=section.heading or f"section{i}",
                    attrs={
                        "path": normalize_path(rel),
                        "heading": section.heading,
                        "text": section.text,
                        "seq": i,
                    },
                    provenance=prov,
                )
            )
            edges.append(
                Edge(src=decision_id, dst=chunk_id, kind=EdgeKind.CONTAINS, provenance=prov)
            )

        mentions = extract_mentions(adr.body, code_exts)
        targets, unresolved = resolve_mentions(mentions, path_index, name_index)
        for target in sorted(targets):
            edges.append(Edge(src=decision_id, dst=target, kind=EdgeKind.GOVERNS, provenance=prov))

        has_supersedes = False
        if adr.supersedes_num and adr.supersedes_num in num_to_decision:
            superseded = num_to_decision[adr.supersedes_num]
            if superseded != decision_id:
                edges.append(
                    Edge(
                        src=decision_id,
                        dst=superseded,
                        kind=EdgeKind.SUPERSEDES,
                        provenance=prov,
                    )
                )
                has_supersedes = True

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        sg = FileSubgraph(path=rel, content_hash=content_hash, nodes=nodes, edges=edges)
        return sg, has_supersedes, len(targets), unresolved

    @staticmethod
    def _without(sg: FileSubgraph, kind: EdgeKind) -> FileSubgraph:
        return sg.model_copy(update={"edges": [e for e in sg.edges if e.kind is not kind]})
