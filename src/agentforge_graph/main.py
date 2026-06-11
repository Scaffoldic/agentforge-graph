# AGENTFORGE-MANAGED: template:minimal@0.2.4 hash:c05d490b5a1c
"""Entry point for agentforge-graph (the `ckg` console script).

Today this runs a plain AgentForge agent against a task string. The
real CKG subcommands — `ckg index`, `ckg serve-mcp`, `ckg map`, etc.
— land with feat-002 (ingestion) and feat-008 (MCP serving); see
`docs/features/` and `docs/features/TRACKER.md`. Engine config is read
from `ckg.yaml`; framework config from `agentforge.yaml`.
"""

from __future__ import annotations

import asyncio
import sys

from agentforge import Agent
from dotenv import load_dotenv

load_dotenv()


async def run_agent(task: str) -> str:
    """Run the agent against `task` and return its output."""
    async with Agent() as agent:
        result = await agent.run(task)
        return str(result.output)


def main() -> None:
    if len(sys.argv) < 2:
        print('Usage: agentforge-graph "<task>"')
        sys.exit(1)
    task = " ".join(sys.argv[1:])
    output = asyncio.run(run_agent(task))
    print(output)


if __name__ == "__main__":
    main()
