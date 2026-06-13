"""Live Bedrock Claude summarizer (feat-012) — env-gated CKG_LIVE_AGENT."""

from __future__ import annotations

import os

import pytest

from agentforge_graph.enrich.bedrock_summarizer import BedrockClaudeSummarizer
from agentforge_graph.enrich.summarizer import FileContext

pytestmark = pytest.mark.skipif(
    os.environ.get("CKG_LIVE_AGENT") != "1",
    reason="live Bedrock Claude summarizer; set CKG_LIVE_AGENT=1 with AWS creds",
)


async def test_live_file_and_repo_summary() -> None:
    s = BedrockClaudeSummarizer()
    ctx = FileContext(
        path="payments/service.py",
        symbols=[
            ("PaymentService", "class PaymentService:"),
            ("charge", "def charge(self, amount, idempotency_key):"),
        ],
        imports=["stripe"],
    )
    fs = await s.summarize_file(ctx, 120)
    assert fs.text and "payment" in fs.text.lower()
    rs = await s.summarize_repo("api", [("payments/service.py", fs.text)], 120)
    assert rs.text
    assert s.cost_usd > 0
