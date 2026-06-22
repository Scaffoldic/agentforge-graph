"""ENH-024: clone/fetch a workspace member named by a git URL.

A `workspace.yaml` member can be a **git/github URL** instead of a local path;
the build clones it into a managed checkout under the workspace
(``<workspace-dir>/.checkouts/<slug>``, git-ignored) so `ckg build --workspace`
can build repos by URL. We **shell out to ``git``** and inherit the operator's
ambient auth (ssh agent / credential helper) — we never handle credentials.

Deterministic and framework-free (subprocess only).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

CHECKOUTS_DIRNAME = ".checkouts"


class CheckoutError(RuntimeError):
    """A git clone/fetch/checkout failed (or git is unavailable)."""


def _git(*args: str) -> None:
    try:
        subprocess.run(["git", *args], capture_output=True, text=True, check=True)
    except FileNotFoundError as exc:  # git not installed
        raise CheckoutError("git is not on PATH") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise CheckoutError(f"git {' '.join(args)} failed: {detail}") from exc


def ensure_gitignore(checkouts_dir: Path) -> None:
    """Make the managed checkout area exist and be git-ignored in full."""
    checkouts_dir.mkdir(parents=True, exist_ok=True)
    gi = checkouts_dir / ".gitignore"
    if not gi.exists():
        gi.write_text("*\n")


def ensure_checkout(
    git_url: str,
    dest: Path,
    *,
    ref: str | None = None,
    fetch: bool = True,
    shallow: bool = True,
) -> Path:
    """Clone ``git_url`` into ``dest`` (first run) or fetch + update (subsequent),
    optionally pinned to ``ref`` (branch/tag/sha). Returns ``dest``.

    - first clone: shallow (``--depth 1``) unless a ``ref`` is pinned (a pinned
      ref may need history) — then a full clone + checkout.
    - existing checkout + ``fetch``: fetch, then ``checkout <ref>`` if pinned,
      else ``pull --ff-only`` to advance the current branch.
    """
    dest = Path(dest)
    ensure_gitignore(dest.parent)
    pin = f" @ {ref}" if ref else ""
    if not (dest / ".git").exists():
        logger.info("checkout: cloning %s%s → %s", git_url, pin, dest)
        args = ["clone"]
        if shallow and not ref:
            args += ["--depth", "1"]
        args += [git_url, str(dest)]
        _git(*args)
        if ref:
            _git("-C", str(dest), "checkout", ref)
    elif fetch:
        logger.info("checkout: fetching %s%s", dest, pin)
        _git("-C", str(dest), "fetch", "--tags", "--prune", "origin")
        if ref:
            _git("-C", str(dest), "checkout", ref)
        else:
            _git("-C", str(dest), "pull", "--ff-only")
    else:
        logger.debug("checkout: using existing %s (no fetch)", dest)
    return dest
