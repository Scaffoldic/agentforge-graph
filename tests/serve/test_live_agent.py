"""Env-gated agent-in-the-loop: a real AgentForge agent with the CKG toolset
answers a fixture question. Needs Anthropic creds + CKG_LIVE_AGENT=1."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"

pytestmark = pytest.mark.skipif(
    os.environ.get("CKG_LIVE_AGENT") != "1",
    reason="live agent loop; set CKG_LIVE_AGENT=1 with Anthropic + AWS creds",
)


async def test_agent_uses_ckg_tools(tmp_path: Path) -> None:
    from agentforge import Agent

    from agentforge_graph.ingest import CodeGraph
    from agentforge_graph.serve import code_graph_tools

    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    cg = await CodeGraph.index(repo_path=repo, embed=True)  # real Bedrock embeddings
    await cg.close()

    agent = Agent(model="anthropic:claude-haiku-4-5", tools=code_graph_tools(repo))
    result = await agent.run("Which functions call `square`? Use the ckg tools.")
    answer = str(result.output).lower()
    assert "cube" in answer or "area" in answer
