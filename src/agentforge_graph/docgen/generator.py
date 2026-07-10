"""``DocGenerator`` (feat-016) — orchestrates grounded docs.

seed → compose (Agent loop) → verify citations → emit draft + manifest entry,
plus the freshness/review surface: dirty-aware ``update``, ``list_docs``,
``diff`` (regenerate vs on-disk), and ``promote`` (the human gate).
"""

from __future__ import annotations

import difflib
import re
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from .citations import verify_citations
from .errors import DocgenError, PromoteRequired
from .manifest import Manifest, content_sha
from .recipes import get_recipe
from .runner import AgentDocRunner
from .staleness import DOCS_CONSUMER, is_stale, stale_docs
from .templates.base import get_template
from .types import (
    DOC_LANG_VERSION,
    STATUS_DRAFT,
    DocArtifact,
    DocTarget,
    DocType,
    Footnote,
)

if TYPE_CHECKING:
    from agentforge_core.contracts.llm import LLMClient

    from agentforge_graph.config import ConfigSource, DocGenConfig
    from agentforge_graph.ingest import CodeGraph
    from agentforge_graph.ingest.incremental import DirtySet


def _slug(scope: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", scope).strip("-") or "root"


class DocGenerator:
    """Generates and maintains grounded docs for one repository/config."""

    def __init__(
        self,
        cg: CodeGraph,
        cfg: DocGenConfig,
        *,
        repo_path: str | Path,
        config: ConfigSource = None,
        model: str | LLMClient | None = None,
    ) -> None:
        self._cg = cg
        self._cfg = cfg
        self._repo_path = Path(repo_path)
        self._config = config
        self._runner = AgentDocRunner(cfg, repo_path=str(repo_path), config=config, model=model)

    # --- generation ----------------------------------------------------------

    async def generate(self, target: DocTarget) -> DocArtifact:
        """Generate one doc: seed → Agent compose → verify → write draft → record."""
        full, source_ids, footnotes, commit = await self._compose(target)
        rel = self._doc_relpath(target)
        abs_path = self._repo_path / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_text(full)

        artifact = DocArtifact(
            type=target.type,
            path=rel,
            status=STATUS_DRAFT,
            synced_commit=commit,
            doc_lang_version=DOC_LANG_VERSION,
            source_ids=source_ids,
            scope=target.scope,
            footnotes=footnotes,
            content_sha=content_sha(full),
        )
        self._manifest().upsert(artifact)
        return artifact

    async def update(self) -> list[DocArtifact]:
        """Regenerate only the docs whose source symbols were dirtied (feat-004
        reuse), then mark those symbols clean for the ``docs`` consumer."""
        manifest = self._manifest()
        dirty = self._dirtyset()
        dirty_ids = await dirty.dirty_for(DOCS_CONSUMER)
        todo = stale_docs(manifest.all(), dirty_ids)

        regenerated: list[DocArtifact] = []
        for art in todo:
            regenerated.append(await self.generate(DocTarget(type=art.type, scope=art.scope)))

        covered = {sid for art in todo for sid in art.source_ids}
        cleaned = [i for i in dirty_ids if i in covered]
        if cleaned:
            await dirty.mark_clean(DOCS_CONSUMER, cleaned)
        return regenerated

    # --- review surface ------------------------------------------------------

    async def list_docs(self) -> list[DocArtifact]:
        """Every generated doc with its ``stale`` flag computed (dirty source,
        moved index commit, or a bumped doc_lang_version)."""
        manifest = self._manifest()
        dirty = set(await self._dirtyset().dirty_for(DOCS_CONSUMER))
        head = self._git_commit()
        out: list[DocArtifact] = []
        for a in manifest.all():
            stale = is_stale(a, dirty, head) or a.doc_lang_version != DOC_LANG_VERSION
            out.append(replace(a, stale=stale))
        return out

    async def diff(self, path: str) -> str:
        """Unified diff of the on-disk doc vs a fresh regeneration — what
        ``update`` would change."""
        art = self._manifest().get(path)
        if art is None:
            raise DocgenError(f"no generated doc recorded at {path!r}")
        abs_path = self._repo_path / path
        current = abs_path.read_text() if abs_path.exists() else ""
        full, *_ = await self._compose(DocTarget(type=art.type, scope=art.scope))
        return "".join(
            difflib.unified_diff(
                current.splitlines(keepends=True),
                full.splitlines(keepends=True),
                fromfile=f"{path} (on disk)",
                tofile=f"{path} (regenerated)",
            )
        )

    def promote(self, path: str) -> DocArtifact:
        """Flip a draft to ``accepted`` — the human review gate."""
        manifest = self._manifest()
        if manifest.get(path) is None:
            raise DocgenError(f"no generated doc recorded at {path!r}")
        return manifest.promote(path)

    # --- opt-in flywheel -----------------------------------------------------

    async def sync(self) -> int:
        """Re-ingest **accepted** docs into the graph as ``llm``-sourced
        ``DocChunk`` nodes that ``DESCRIBES`` their cited symbols (and, when embed
        is enabled, are embedded for search). Opt-in (``round_trip``) and gated on
        promotion. Tagging them ``Source.LLM`` is the anti-echo-chamber guarantee:
        recipes/tools floor at ``>= parsed``, so a synced doc can inform search but
        is never a citable ground-truth fact."""
        if not self._cfg.round_trip:
            raise DocgenError(
                "docgen.round_trip is off; enable it to feed generated docs back into the graph"
            )
        all_docs = self._manifest().all()
        accepted = [a for a in all_docs if a.accepted]
        if not accepted:
            if all_docs:
                raise PromoteRequired("no accepted docs to sync — promote reviewed drafts first")
            return 0

        repo = self._repo_path.resolve().name
        commit = self._git_commit()
        store = self._cg.store
        embedder = self._embedder()
        for art in accepted:
            sg = await self._doc_subgraph(art, repo, commit)
            await store.graph.upsert(sg)
            if embedder is not None:
                await self._embed_doc(embedder, art, sg)
        return len(accepted)

    async def _doc_subgraph(self, art: DocArtifact, repo: str, commit: str):  # type: ignore[no-untyped-def]
        from agentforge_graph.core import (
            Edge,
            EdgeKind,
            FileSubgraph,
            Node,
            NodeKind,
            Provenance,
            SymbolID,
        )

        abs_path = self._repo_path / art.path
        text = abs_path.read_text() if abs_path.exists() else ""
        chunk_id = SymbolID.for_symbol("docgen", repo, art.path, "generated.")
        prov = Provenance.llm(f"docgen@{DOC_LANG_VERSION}", 1.0, commit)
        node = Node(
            id=chunk_id,
            kind=NodeKind.DOC_CHUNK,
            name=f"generated:{art.path}",
            attrs={
                "path": art.path,
                "text": text,
                "doc_source": "generated",  # distinguishes docgen output from ingested docs
                "doc_type": art.type.value,
            },
            provenance=prov,
        )
        edges: list[Edge] = []
        seen: set[str] = set()
        for f in art.footnotes:
            if f.ref.id in seen or await self._cg.store.graph.get(f.ref.id) is None:
                continue
            seen.add(f.ref.id)
            edges.append(Edge(src=chunk_id, dst=f.ref.id, kind=EdgeKind.DESCRIBES, provenance=prov))
        return FileSubgraph(path=art.path, content_hash=art.content_sha, nodes=[node], edges=edges)

    def _embedder(self) -> object | None:
        from agentforge_graph.config import EmbedConfig
        from agentforge_graph.embed import embedder_from_config

        cfg = EmbedConfig.load(self._config)
        if not cfg.enabled:
            return None
        return embedder_from_config(cfg)

    async def _embed_doc(self, embedder: object, art: DocArtifact, sg: object) -> None:
        from agentforge_graph.core import Embedded, NodeKind
        from agentforge_graph.embed import Embedder

        if not isinstance(embedder, Embedder):
            return
        node = sg.nodes[0]  # type: ignore[attr-defined]
        vectors = await embedder.embed([str(node.attrs.get("text", ""))], "document")
        await self._cg.store.vectors.delete_where({"ref": node.id})
        await self._cg.store.vectors.upsert(
            [
                Embedded(
                    ref=node.id,
                    vector=vectors[0],
                    kind=NodeKind.DOC_CHUNK,
                    attrs={
                        "path": art.path,
                        "source_type": "generated-doc",
                        "model": embedder.name,
                    },
                )
            ]
        )

    # --- internals -----------------------------------------------------------

    async def _compose(
        self, target: DocTarget
    ) -> tuple[str, tuple[str, ...], tuple[Footnote, ...], str]:
        recipe = get_recipe(target.type)
        pack = await recipe.seed(self._cg, target)
        template = get_template(target.type)
        body, prov = await self._runner.compose(pack, template)
        verified = verify_citations(body, prov, require_citations=self._cfg.require_citations)
        commit = self._git_commit()
        full = self._stamp(verified.body, target, commit)
        return full, prov.source_ids(), verified.footnotes, commit

    def _manifest(self) -> Manifest:
        return Manifest(self._repo_path / self._cfg.output_root)

    def _dirtyset(self) -> DirtySet:
        from agentforge_graph.config import StoreConfig
        from agentforge_graph.ingest.incremental import DirtySet
        from agentforge_graph.store import resolve_root

        root = resolve_root(self._repo_path, StoreConfig.load(self._config))
        return DirtySet(root)

    def _doc_relpath(self, target: DocTarget) -> str:
        root = self._cfg.output_root.rstrip("/")
        if target.type is DocType.COMPONENT and target.scope:
            return f"{root}/component/{_slug(target.scope)}.md"
        return f"{root}/{target.type.value}.md"

    def _stamp(self, body: str, target: DocTarget, commit: str) -> str:
        header = (
            "<!-- Generated by CKG docgen — do not edit by hand.\n"
            f"     type: {target.type.value} · synced @{commit or 'unknown'} · "
            f"doc_lang_version {DOC_LANG_VERSION} -->\n\n"
        )
        return header + body.strip() + "\n"

    def _git_commit(self) -> str:
        from agentforge_graph.ingest.codegraph import _git_commit

        return _git_commit(self._repo_path)
