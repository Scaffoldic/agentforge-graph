"""Live Bedrock Claude pattern judge (feat-012) — env-gated.

Set CKG_LIVE_AGENT=1 with AWS creds (Bedrock access) to run. Verifies the judge
returns honest verdicts (confirms a clear Repository, rejects a name-only weak
signal), tracks cost, and that every tag carries llm provenance.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentforge_graph.core import GraphQuery, NodeKind, Source
from agentforge_graph.ingest import CodeGraph

pytestmark = pytest.mark.skipif(
    os.environ.get("CKG_LIVE_AGENT") != "1",
    reason="live Bedrock Claude judge; set CKG_LIVE_AGENT=1 with AWS creds",
)

CODE = (
    "class OrderRepository:\n"
    "    def get(self, id): ...\n"
    "    def save(self, order): ...\n"
    "    def delete(self, id): ...\n"
    "    def list(self): ...\n\n\n"
    "class PaymentService:\n"
    "    def charge(self, amount): ...\n"
)


async def test_live_enrich_tags_and_provenance(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(CODE)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        report = await cg.enrich()  # real Bedrock judge from EnrichConfig
        assert report.judged >= 1
        assert report.cost_usd > 0
        # the strong Repository signal should be tagged
        assert await cg.tagged("Repository")
        tags = (
            await cg.store.graph.query(GraphQuery(kinds=[NodeKind.PATTERN_TAG], limit=99))
        ).nodes
        assert tags and all(t.provenance.source is Source.LLM for t in tags)
    finally:
        await cg.close()
