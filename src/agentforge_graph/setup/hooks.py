"""Agent nudge hooks (feat-013, chunk 5).

``ckg setup --hooks`` appends a short **managed block** to the repo's
agent-instructions file (``AGENTS.md`` / ``CLAUDE.md``) telling the agent to
prefer the ``ckg_*`` tools over grep/glob for structural questions. Repo-level
(matches the ``.mcp.json`` default), portable (every ``AGENTS.md``-aware agent
reads it), and inherently non-blocking — it adds context, never overrides the
agent's tool choices.

The block is fenced by HTML-comment markers so it is idempotent (replaced in
place) and ``--undo``-removable (exactly the marked block, nothing the user
wrote). If neither file exists, a minimal ``AGENTS.md`` is created with just the
block.
"""

from __future__ import annotations

from pathlib import Path

HOOK_START = "<!-- agentforge-graph:start -->"
HOOK_END = "<!-- agentforge-graph:end -->"
HOOK_FILES = ("AGENTS.md", "CLAUDE.md")

_BODY = """## Prefer the code graph
For structural questions (callers, impact, routes, where-defined), use the
ckg_* MCP tools instead of grep/glob — cheaper and grounded. Fall back to file
reads only when the graph can't answer."""


def _block() -> str:
    return f"{HOOK_START}\n{_BODY}\n{HOOK_END}\n"


def hook_targets(repo: Path) -> list[Path]:
    """Existing instruction files to update, or ``[AGENTS.md]`` to create."""
    existing = [repo / name for name in HOOK_FILES if (repo / name).exists()]
    return existing or [repo / HOOK_FILES[0]]


def _strip_block(text: str) -> str:
    """Remove a managed block (markers inclusive) from ``text``; return the rest
    trimmed of surrounding blank lines. Unchanged if no block is present."""
    if HOOK_START not in text:
        return text.strip("\n")
    pre, _, rest = text.partition(HOOK_START)
    _, _, post = rest.partition(HOOK_END)
    return (pre.rstrip("\n") + "\n" + post.lstrip("\n")).strip("\n")


def apply_hooks(repo: Path) -> list[tuple[Path, str]]:
    """Install/refresh the nudge block in each target. Returns (path, status) —
    ``created`` / ``added`` / ``updated`` / ``noop``."""
    block = _block()
    results: list[tuple[Path, str]] = []
    for path in hook_targets(repo):
        existed = path.exists()
        before = path.read_text() if existed else ""
        had = HOOK_START in before
        body = _strip_block(before)
        new = f"{body}\n\n{block}" if body else block
        if before == new:
            results.append((path, "noop"))
            continue
        path.write_text(new)
        results.append((path, "updated" if had else ("added" if existed else "created")))
    return results


def undo_hooks(repo: Path) -> list[tuple[Path, str]]:
    """Remove our managed block from any instruction file. Returns (path,
    status) — ``removed`` / ``removed-file`` / ``skipped``."""
    results: list[tuple[Path, str]] = []
    for name in HOOK_FILES:
        path = repo / name
        if not path.exists():
            continue
        before = path.read_text()
        if HOOK_START not in before:
            results.append((path, "skipped"))
            continue
        body = _strip_block(before)
        if body:
            path.write_text(body + "\n")
            results.append((path, "removed"))
        else:
            path.unlink()
            results.append((path, "removed-file"))
    return results
