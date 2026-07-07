"""feat-014: git-branch helpers for watch mode.

Read the current branch/HEAD and decide whether watch is active on it. Pure
stdlib + a light git read; framework-free (ADR-0001).
"""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path


def current_branch(repo: str | Path) -> str:
    """The current branch name, or "" when detached / not a git repo.

    Read straight from ``.git/HEAD`` (``ref: refs/heads/<branch>``) so no
    subprocess is needed — the watch loop polls this cheaply on git events."""
    head = Path(repo) / ".git" / "HEAD"
    try:
        text = head.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    prefix = "ref: refs/heads/"
    return text[len(prefix) :] if text.startswith(prefix) else ""


def head_ref(repo: str | Path) -> str:
    """The raw HEAD contents (branch ref or detached sha) — the token the loop
    diffs to detect a commit / branch switch."""
    head = Path(repo) / ".git" / "HEAD"
    try:
        return head.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def branch_active(branch: str, include: list[str], exclude: list[str]) -> bool:
    """Whether watch should run on ``branch`` given include/exclude globs.

    Exclude wins over include. An empty branch (detached HEAD / no git) is treated
    as active — the developer explicitly started ``ckg watch`` there, and there is
    no branch name to gate on."""
    if not branch:
        return True
    if any(_match(branch, g) for g in exclude):
        return False
    return any(_match(branch, g) for g in include)


def _match(branch: str, glob: str) -> bool:
    # fnmatch (not pathlib full_match): a branch is not a path — its `*` must
    # cross `/` so `*` matches `feature/x` and `release/*` matches `release/0.6.3`.
    return fnmatch(branch, glob)
