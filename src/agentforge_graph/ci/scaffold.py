"""feat-014: write the scaffolded CI workflow with feat-013's managed-marker
discipline — idempotent, and never clobbering an unmanaged file without
``--force``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .github import MARKER, WORKFLOW_REL_PATH, render_workflow

PROVIDERS = ("github",)


class CiInitError(Exception):
    """Raised when the scaffolder refuses to act (unknown provider, or would
    clobber an unmanaged file without ``--force``)."""


@dataclass
class CiInitResult:
    path: Path
    action: str  # created | updated | noop | overwritten | printed
    content: str


def scaffold_workflow(
    repo: str | Path,
    *,
    provider: str = "github",
    mode: str = "incremental",
    embed: bool = True,
    enrich: bool = False,
    extras: list[str] | None = None,
    force: bool = False,
    print_only: bool = False,
) -> CiInitResult:
    if provider not in PROVIDERS:
        raise CiInitError(f"unknown CI provider {provider!r}; supported: {', '.join(PROVIDERS)}")
    content = render_workflow(mode=mode, embed=embed, enrich=enrich, extras=extras)
    target = Path(repo) / WORKFLOW_REL_PATH

    if print_only:
        return CiInitResult(target, "printed", content)

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if MARKER not in existing and not force:
            raise CiInitError(
                f"{target} exists and is not managed by agentforge-graph. "
                "Refusing to overwrite it — pass --force to replace it."
            )
        if existing == content:
            return CiInitResult(target, "noop", content)
        action = "overwritten" if MARKER not in existing else "updated"
        target.write_text(content, encoding="utf-8")
        return CiInitResult(target, action, content)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return CiInitResult(target, "created", content)
