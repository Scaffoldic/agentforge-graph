"""Live OpenAI embeddings (ENH-003 phase 2) — env-gated.

Set ``CKG_LIVE_OPENAI=1`` with ``OPENAI_API_KEY`` to run (needs the ``openai``
extra). Verifies a real embedding of the requested dimensionality."""

from __future__ import annotations

import os

import pytest

from agentforge_graph.embed.openai import OpenAIEmbedder

pytestmark = pytest.mark.skipif(
    os.environ.get("CKG_LIVE_OPENAI") != "1",
    reason="live OpenAI embeddings; set CKG_LIVE_OPENAI=1 with OPENAI_API_KEY",
)


async def test_live_openai_embed_dimensionality() -> None:
    emb = OpenAIEmbedder(model="text-embedding-3-small", dim=256)
    vecs = await emb.embed(["the quick brown fox"], input_type="document")
    assert len(vecs) == 1
    assert len(vecs[0]) == 256
    assert any(abs(x) > 0 for x in vecs[0])
