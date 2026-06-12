"""Guardrails: response_token_cap trims with a note (no silent caps)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from agentforge_graph.ingest import CodeGraph
from agentforge_graph.serve.engine import _Engine
from agentforge_graph.serve.tools import CkgSearch

FIXTURES = Path(__file__).parent.parent / "ingest" / "fixtures" / "python"
TINY_CAP_YAML = "embed:\n  driver: fake\n  dim: 16\nserve:\n  response_token_cap: 5\n"


async def test_response_token_cap_truncates_with_note(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shutil.copytree(FIXTURES, repo)
    (repo / "ckg.yaml").write_text(TINY_CAP_YAML)
    cfg = str(repo / "ckg.yaml")
    cg = await CodeGraph.index(repo_path=repo, config=cfg, embed=True)
    await cg.close()
    engine = _Engine(repo, cfg)
    try:
        out = await CkgSearch(engine).run(query="circle area square", k=8, mode="context")
        data = json.loads(out)
        assert data["truncated"] is True
        assert any("response truncated" in n for n in data.get("notes", []))
    finally:
        await engine.close()
