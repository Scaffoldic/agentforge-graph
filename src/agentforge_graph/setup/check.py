"""Post-write connection check (feat-013, chunk 3).

After ``ckg setup`` writes the config, optionally confirm the wiring actually
works: spawn the configured ``ckg serve-mcp`` over MCP stdio, run an
``initialize`` + ``tools/list``, and assert the ``ckg_status`` tool is exposed.

It **never raises** — any failure is returned as a structured result so the CLI
can print "wrote config, but the server didn't answer — try `ckg serve-mcp
--repo .` manually" rather than a stack trace. Skip it with ``--no-check``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    detail: str


async def connection_check(
    repo: Path, *, command: str = "ckg", timeout: float = 20.0
) -> CheckResult:
    """Spawn ``command serve-mcp --repo <repo>`` and verify it answers MCP with
    the CKG tools. Returns a :class:`CheckResult`; never raises."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:  # pragma: no cover - mcp is a base dep
        return CheckResult(False, "mcp client SDK unavailable")

    params = StdioServerParameters(command=command, args=["serve-mcp", "--repo", str(repo)])
    try:
        async with asyncio.timeout(timeout):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    names = {t.name for t in listed.tools}
        if "ckg_status" in names:
            return CheckResult(True, f"server answered with {len(names)} tools")
        return CheckResult(False, "server started but ckg_status is not exposed")
    except TimeoutError:
        return CheckResult(False, f"server did not respond within {timeout:.0f}s")
    except Exception as exc:  # noqa: BLE001 - any spawn/handshake failure is a soft fail
        return CheckResult(False, f"{type(exc).__name__}: {exc}")
