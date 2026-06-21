"""Where a repo's index artifacts live (ENH-018).

By default the store is the repo-relative ``.ckg/`` — the laptop story
(``store.path``, default ``.ckg``). When a ``store.central_root`` is configured,
each repo instead gets a **stable per-repo subdir** under that root, so a team or
CI can host many repos' indexes centrally without them colliding. The per-repo
key prefers the git remote (``org/repo`` — host-independent, so the key is the
same on every machine) and falls back to ``<dirname>-<hash>`` of the canonical
path when there is no remote.

This is the single place the ``.ckg`` root is computed; every caller resolves
through :func:`resolve_root` rather than re-deriving ``repo_path / store.path``.

Stdlib-only, no ``agentforge`` import (ADR-0001).
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentforge_graph.config import StoreConfig

_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text).strip("-")


def _git_remote(repo_path: Path) -> str | None:
    """``remote.origin.url`` for ``repo_path``, or ``None`` if there is no git
    remote (or git is unavailable)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_path), "config", "--get", "remote.origin.url"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def repo_key(repo_path: str | Path) -> str:
    """A stable, filesystem-safe identifier for a repo, used to namespace its
    index under a central root.

    Prefers the git remote's trailing ``org/repo`` (slugified, host-independent);
    falls back to ``<dirname>-<8 hex of the canonical path>`` when there is no
    remote (documented: a remote-less repo keys by its absolute path, so the key
    is machine-local).
    """
    path = Path(repo_path).resolve()
    remote = _git_remote(path)
    if remote:
        tail = remote[:-4] if remote.endswith(".git") else remote
        parts = [p for p in re.split(r"[/:]", tail) if p]
        if parts:
            key = _slug("/".join(parts[-2:]))
            if key:
                return key
    digest = hashlib.sha1(str(path).encode()).hexdigest()[:8]
    return f"{_slug(path.name) or 'repo'}-{digest}"


def resolve_root(repo_path: str | Path, cfg: StoreConfig) -> Path:
    """The directory holding this repo's index artifacts.

    - ``store.central_root`` **unset** → ``repo_path / store.path`` (the in-repo
      ``.ckg``; unchanged behavior, including an absolute ``store.path``).
    - ``store.central_root`` **set** → ``central_root / repo_key(repo_path)`` — a
      stable per-repo subdir, so two repos under one central root never collide.
    """
    if cfg.central_root:
        return Path(cfg.central_root).expanduser() / repo_key(repo_path)
    return Path(repo_path) / cfg.path


def is_read_only(cfg: StoreConfig) -> bool:
    """Whether the store should be treated as consume-only (ENH-018).

    True when ``store.read_only`` is set in config (the durable, deployment-level
    switch) or when ``$CKG_READ_ONLY`` is truthy (set per-invocation by the
    ``--read-only`` CLI flag). Write verbs refuse, and opening a missing index
    errors instead of creating one.
    """
    if cfg.read_only:
        return True
    return os.environ.get("CKG_READ_ONLY", "").strip().lower() in ("1", "true", "yes", "on")
