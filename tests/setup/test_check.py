"""feat-013 chunk 3: the connection check soft-fails (never raises) when the
server can't be spawned. The live success path is exercised end-to-end,
env-gated, in validation — not in the unit gate."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.setup.check import connection_check


async def test_bad_command_soft_fails(tmp_path: Path) -> None:
    result = await connection_check(tmp_path, command="ckg-no-such-binary-xyz", timeout=5.0)
    assert result.ok is False
    assert result.detail  # a reason, not a stack trace
