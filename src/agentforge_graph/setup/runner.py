"""Orchestrate ``ckg setup`` (feat-013, chunk 3): plan → render → confirm →
write → connection check (and the ``--undo`` path).

The flow is dependency-injected (``confirm``/``out``/``check_fn``) so it is
unit-testable without real stdin, files-of-record, or a spawned server.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from .check import CheckResult, connection_check
from .merge import undo_entry
from .plan import build_plan, render_plan, render_undo
from .registry import all_adapters


def _default_confirm(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _undo_paths(repo: Path, scope: str, agents: list[str] | None) -> list[tuple[Path, str]]:
    seen: set[Path] = set()
    results: list[tuple[Path, str]] = []
    for adapter in all_adapters(agents):
        path = adapter.config_path(repo, scope)
        if path is None:
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        results.append((path, undo_entry(path)))
    return results


async def run_setup(
    repo: Path,
    *,
    scope: str = "project",
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str = "",
    agents: list[str] | None = None,
    hooks: bool = False,
    do_print: bool = False,
    assume_yes: bool = False,
    do_check: bool = True,
    undo: bool = False,
    force: bool = False,
    confirm: Callable[[str], bool] = _default_confirm,
    out: Callable[[str], None] = print,
    check_fn: Callable[[Path], Awaitable[CheckResult]] = connection_check,
) -> int:
    """Run ``ckg setup``. Returns a process exit code (0 ok, non-zero on a
    refused conflict). Raises :class:`SetupError` for bad input (caught + printed
    by the CLI)."""
    from .hooks import apply_hooks, hook_targets, undo_hooks

    if undo:
        # Reverse everything we may have written, regardless of --hooks.
        results = _undo_paths(repo, scope, agents) + undo_hooks(repo)
        out(render_undo(results))
        return 0

    plan = build_plan(
        repo,
        scope,
        transport=transport,
        host=host,
        port=port,
        token=token,
        allow=agents,
        force=force,
    )
    out(render_plan(plan))
    if hooks:
        names = ", ".join(p.name for p in hook_targets(repo))
        out(f"  + nudge block → {names}")

    conflicts = [t for t in plan.targets if t.status == "conflict"]
    if conflicts and not force:
        paths = ", ".join(str(t.path) for t in conflicts)
        out(f"\nrefusing to overwrite a 'ckg' entry you authored in: {paths}")
        out("re-run with --force to replace it, or remove it yourself.")
        return 2

    if do_print:
        return 0
    if not plan.writable and not hooks:
        out("\nnothing to do — config already up to date.")
        return 0

    if not assume_yes and not confirm("\nApply? [y/N] "):
        out("aborted — nothing written.")
        return 0

    from .merge import write_entry

    for target in plan.writable:
        status = write_entry(target.path, plan.entry, force=force)
        out(f"  {status}: {target.path}")

    if hooks:
        for path, status in apply_hooks(repo):
            out(f"  {status}: {path}")

    if do_check:
        result = await check_fn(repo)
        out(f"\nconnection check: {'connected ✓' if result.ok else 'warning'} — {result.detail}")
        if not result.ok:
            out("the config was written; try `ckg serve-mcp --repo .` manually if needed.")
    return 0
