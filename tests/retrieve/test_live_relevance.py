"""Env-gated live relevance smoke against real Bedrock Cohere embeddings.
Set CKG_LIVE_BEDROCK=1 with AWS creds to run."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from agentforge_graph.embed import BedrockEmbedder
from agentforge_graph.ingest import CodeGraph

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"

pytestmark = pytest.mark.skipif(
    os.environ.get("CKG_LIVE_BEDROCK") != "1",
    reason="live Bedrock relevance smoke; set CKG_LIVE_BEDROCK=1 with AWS creds",
)


async def test_relevance_finds_area(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    emb = BedrockEmbedder(dim=1024)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        await cg.embed(embedder=emb)
        pack = await cg.retrieve("compute the area of a circle", mode="context", k=3, embedder=emb)
        # the area method (or its chunk) should surface near the top
        joined = " ".join(i.name + " " + (i.code or "") for i in pack.items)
        assert "area" in joined.lower()
    finally:
        await cg.close()
