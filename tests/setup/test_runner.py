"""feat-013 chunk 3: run_setup orchestration — plan/diff, confirm, write, undo,
conflict, dedupe, and the injected connection check."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentforge_graph.setup.check import CheckResult
from agentforge_graph.setup.merge import MARKER_KEY, MARKER_VALUE
from agentforge_graph.setup.runner import run_setup


async def _ok_check(_repo: Path) -> CheckResult:
    return CheckResult(True, "server answered with 6 tools")


async def _bad_check(_repo: Path) -> CheckResult:
    return CheckResult(False, "did not respond")


def _capture() -> tuple[list[str], object]:
    lines: list[str] = []
    return lines, lambda s: lines.append(s)


def _read(p: Path) -> dict:
    return json.loads(p.read_text())


async def test_print_only_writes_nothing(tmp_path: Path) -> None:
    lines, out = _capture()
    rc = await run_setup(tmp_path, scope="project", agents=["mcp_json"], do_print=True, out=out)
    assert rc == 0
    assert not (tmp_path / ".mcp.json").exists()
    assert any("Plan" in ln for ln in lines)


async def test_apply_with_yes_writes_and_checks(tmp_path: Path) -> None:
    lines, out = _capture()
    rc = await run_setup(
        tmp_path,
        scope="project",
        agents=["mcp_json"],
        assume_yes=True,
        out=out,
        check_fn=_ok_check,
    )
    assert rc == 0
    doc = _read(tmp_path / ".mcp.json")
    assert doc["mcpServers"]["ckg"]["args"] == ["serve-mcp", "--repo", "."]
    assert doc["mcpServers"]["ckg"][MARKER_KEY] == MARKER_VALUE
    assert any("connected ✓" in ln for ln in lines)


async def test_confirm_no_aborts(tmp_path: Path) -> None:
    lines, out = _capture()
    rc = await run_setup(
        tmp_path,
        scope="project",
        agents=["mcp_json"],
        out=out,
        confirm=lambda _p: False,
        check_fn=_ok_check,
    )
    assert rc == 0
    assert not (tmp_path / ".mcp.json").exists()
    assert any("aborted" in ln for ln in lines)


async def test_no_check_skips_check(tmp_path: Path) -> None:
    called = False

    async def _spy(_repo: Path) -> CheckResult:
        nonlocal called
        called = True
        return CheckResult(True, "x")

    await run_setup(
        tmp_path,
        scope="project",
        agents=["mcp_json"],
        assume_yes=True,
        do_check=False,
        out=lambda _s: None,
        check_fn=_spy,
    )
    assert called is False


async def test_failed_check_is_nonfatal(tmp_path: Path) -> None:
    lines, out = _capture()
    rc = await run_setup(
        tmp_path,
        scope="project",
        agents=["mcp_json"],
        assume_yes=True,
        out=out,
        check_fn=_bad_check,
    )
    assert rc == 0  # config still written
    assert (tmp_path / ".mcp.json").exists()
    assert any("warning" in ln for ln in lines)


async def test_idempotent_second_run_noop(tmp_path: Path) -> None:
    lines, out = _capture()
    await run_setup(
        tmp_path, agents=["mcp_json"], assume_yes=True, do_check=False, out=lambda _s: None
    )
    rc = await run_setup(tmp_path, agents=["mcp_json"], assume_yes=True, do_check=False, out=out)
    assert rc == 0
    assert any("nothing to do" in ln for ln in lines)


async def test_undo_removes_entry(tmp_path: Path) -> None:
    await run_setup(
        tmp_path, agents=["mcp_json"], assume_yes=True, do_check=False, out=lambda _s: None
    )
    assert (tmp_path / ".mcp.json").exists()
    rc = await run_setup(tmp_path, agents=["mcp_json"], undo=True, out=lambda _s: None)
    assert rc == 0
    assert not (tmp_path / ".mcp.json").exists()


async def test_conflict_refused_without_force(tmp_path: Path) -> None:
    p = tmp_path / ".mcp.json"
    p.write_text(json.dumps({"mcpServers": {"ckg": {"command": "mine"}}}))
    lines, out = _capture()
    rc = await run_setup(tmp_path, agents=["mcp_json"], assume_yes=True, do_check=False, out=out)
    assert rc == 2
    assert _read(p)["mcpServers"]["ckg"] == {"command": "mine"}  # untouched
    assert any("--force" in ln for ln in lines)


async def test_project_scope_dedupes_to_single_target(tmp_path: Path) -> None:
    # Both mcp_json and claude_code point project scope at the same .mcp.json →
    # one write, not two.
    lines, out = _capture()
    await run_setup(tmp_path, scope="project", assume_yes=True, do_check=False, out=out)
    # exactly one ".mcp.json" target line in the rendered plan
    target_lines = [ln for ln in lines if ".mcp.json" in ln and "[" in ln]
    assert len(target_lines) == 1
    # both adapters credited as using it
    assert "Claude Code" in target_lines[0]


async def test_hooks_installed_and_undone(tmp_path: Path) -> None:
    from agentforge_graph.setup.hooks import HOOK_START

    await run_setup(
        tmp_path,
        agents=["mcp_json"],
        hooks=True,
        assume_yes=True,
        do_check=False,
        out=lambda _s: None,
    )
    assert (tmp_path / ".mcp.json").exists()
    assert HOOK_START in (tmp_path / "AGENTS.md").read_text()

    # --undo reverses both the MCP entry and the nudge block, even without --hooks.
    await run_setup(tmp_path, agents=["mcp_json"], undo=True, out=lambda _s: None)
    assert not (tmp_path / ".mcp.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()


async def test_hooks_only_still_acts_when_mcp_noop(tmp_path: Path) -> None:
    # MCP already written → plan is noop, but --hooks still has work to do.
    await run_setup(
        tmp_path, agents=["mcp_json"], assume_yes=True, do_check=False, out=lambda _s: None
    )
    lines, out = _capture()
    rc = await run_setup(
        tmp_path,
        agents=["mcp_json"],
        hooks=True,
        assume_yes=True,
        do_check=False,
        out=out,
    )
    assert rc == 0
    assert (tmp_path / "AGENTS.md").exists()
    assert not any("nothing to do" in ln for ln in lines)


async def test_bind_safety_raises(tmp_path: Path) -> None:
    from agentforge_graph.setup import SetupError

    with pytest.raises(SetupError, match="bind-safety"):
        await run_setup(
            tmp_path,
            agents=["mcp_json"],
            transport="http",
            host="0.0.0.0",
            assume_yes=True,
            do_check=False,
            out=lambda _s: None,
        )
