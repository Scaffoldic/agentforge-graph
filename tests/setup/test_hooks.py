"""feat-013 chunk 5: AGENTS.md/CLAUDE.md nudge block — create/idempotent/
update, preservation, and undo."""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.setup.hooks import (
    HOOK_END,
    HOOK_START,
    apply_hooks,
    undo_hooks,
)


def test_creates_agents_md_when_none(tmp_path: Path) -> None:
    res = apply_hooks(tmp_path)
    agents = tmp_path / "AGENTS.md"
    assert res == [(agents, "created")]
    text = agents.read_text()
    assert HOOK_START in text and HOOK_END in text
    assert "ckg_* MCP tools" in text


def test_appends_preserving_existing(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# My project\n\nSome rules.\n")
    res = apply_hooks(tmp_path)
    assert res == [(agents, "added")]
    text = agents.read_text()
    assert text.startswith("# My project")
    assert "Some rules." in text
    assert HOOK_START in text


def test_idempotent(tmp_path: Path) -> None:
    apply_hooks(tmp_path)
    first = (tmp_path / "AGENTS.md").read_text()
    res = apply_hooks(tmp_path)
    assert res == [(tmp_path / "AGENTS.md", "noop")]
    assert (tmp_path / "AGENTS.md").read_text() == first  # byte-identical


def test_updates_in_place_no_duplicate(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(f"intro\n\n{HOOK_START}\nstale content\n{HOOK_END}\n")
    apply_hooks(tmp_path)
    text = agents.read_text()
    assert text.count(HOOK_START) == 1  # replaced, not duplicated
    assert "stale content" not in text
    assert text.startswith("intro")


def test_updates_existing_claude_md_too(tmp_path: Path) -> None:
    # When CLAUDE.md exists, it's a target (Claude Code reads it).
    (tmp_path / "CLAUDE.md").write_text("# Claude rules\n")
    res = dict((p.name, s) for p, s in apply_hooks(tmp_path))
    assert res == {"CLAUDE.md": "added"}
    assert HOOK_START in (tmp_path / "CLAUDE.md").read_text()
    assert not (tmp_path / "AGENTS.md").exists()  # didn't create a second file


def test_undo_removes_block_keeps_content(tmp_path: Path) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Keep me\n")
    apply_hooks(tmp_path)
    res = undo_hooks(tmp_path)
    assert res == [(agents, "removed")]
    text = agents.read_text()
    assert "# Keep me" in text
    assert HOOK_START not in text


def test_undo_removes_file_we_created(tmp_path: Path) -> None:
    apply_hooks(tmp_path)  # creates AGENTS.md with only our block
    res = undo_hooks(tmp_path)
    assert res == [(tmp_path / "AGENTS.md", "removed-file")]
    assert not (tmp_path / "AGENTS.md").exists()


def test_undo_skips_unmanaged_file(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("# no block here\n")
    res = undo_hooks(tmp_path)
    assert res == [(tmp_path / "AGENTS.md", "skipped")]
    assert (tmp_path / "AGENTS.md").read_text() == "# no block here\n"
