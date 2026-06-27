"""Best-effort install-channel detection for ``ckg --version`` (feat-013 /
FA-001 Phase 1).

**Diagnostic only** — it never changes behavior, it just helps a bug report say
how ``ckg`` was installed. We inspect the interpreter location: a uv tool/cache
prefix ⇒ ``uvx``, a pipx venv ⇒ ``pipx``, otherwise ``pip`` (the common case).
Arguments are injectable so the detection is unit-testable without faking the
real interpreter.
"""

from __future__ import annotations

import sys


def detect_channel(prefix: str | None = None, executable: str | None = None) -> str:
    """Return ``"uvx"`` / ``"pipx"`` / ``"pip"`` for how this ``ckg`` was run."""
    blob = (
        (
            (prefix if prefix is not None else sys.prefix)
            + "|"
            + (executable if executable is not None else sys.executable)
        )
        .lower()
        .replace("\\", "/")
    )
    if "pipx" in blob:
        return "pipx"
    if "/uv/" in blob or "uv/tools" in blob or "archive-v0" in blob:
        return "uvx"
    return "pip"
