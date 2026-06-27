"""Build + render the ``ckg setup`` plan (feat-013, chunk 3).

Given the repo, scope, and selected adapters, compute the target file(s) and
what writing the MCP entry would do to each — **deduped by resolved path** (in
project scope every adapter points at the same ``.mcp.json``). The plan is what
``--print`` shows and what the confirm prompt is about; nothing here writes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .merge import build_entry, load, plan_entry
from .registry import Detection, all_adapters


@dataclass(frozen=True)
class TargetPlan:
    path: Path
    status: str  # create | update | noop | conflict
    used_by: list[str]  # adapter display names that read this file


@dataclass
class SetupPlan:
    repo: Path
    scope: str
    transport: str
    entry: dict[str, object]
    targets: list[TargetPlan] = field(default_factory=list)
    detections: list[tuple[str, Detection]] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)  # adapters with no target for this scope

    @property
    def writable(self) -> list[TargetPlan]:
        return [t for t in self.targets if t.status in ("create", "update")]


def build_plan(
    repo: Path,
    scope: str,
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str = "",
    allow: list[str] | None = None,
    force: bool = False,
) -> SetupPlan:
    # Project scope writes a relative path (portable in a committed file); user
    # scope writes the absolute repo (a global config serves a specific repo).
    repo_arg = "." if scope == "project" else str(repo.resolve())
    entry = build_entry(repo_arg, transport=transport, host=host, port=port, token=token)

    plan = SetupPlan(repo=repo, scope=scope, transport=transport, entry=entry)
    by_path: dict[Path, TargetPlan] = {}
    for adapter in all_adapters(allow):
        det = adapter.detect()
        plan.detections.append((adapter.target.display, det))
        path = adapter.config_path(repo, scope)
        if path is None:
            plan.skipped.append(adapter.target.display)
            continue
        resolved = path.resolve()
        if resolved in by_path:
            by_path[resolved].used_by.append(adapter.target.display)
            continue
        status = plan_entry(load(path), entry, force=force).status
        tp = TargetPlan(path=path, status=status, used_by=[adapter.target.display])
        by_path[resolved] = tp
        plan.targets.append(tp)
    return plan


_SIGN = {"create": "+", "update": "~", "noop": "=", "conflict": "!"}


def render_plan(plan: SetupPlan) -> str:
    lines = ["Detected agents:"]
    for display, det in plan.detections:
        mark = "✓" if det["installed"] else "–"
        lines.append(f"  {mark} {display:<28} {det['note']}")
    lines.append("")
    lines.append(f"Plan (scope: {plan.scope}, transport: {plan.transport}):")
    if not plan.targets:
        lines.append("  (no writable target for this scope)")
    for t in plan.targets:
        sign = _SIGN.get(t.status, "?")
        via = ", ".join(t.used_by)
        lines.append(f"  {sign} {t.path}  [{t.status}]  ({via})")
    if plan.skipped:
        lines.append(f"  – skipped (no {plan.scope} target): {', '.join(plan.skipped)}")
    return "\n".join(lines)


def render_undo(results: list[tuple[Path, str]]) -> str:
    lines = ["Undo:"]
    for path, status in results:
        lines.append(f"  {path}  [{status}]")
    return "\n".join(lines)


__all__ = [
    "SetupPlan",
    "TargetPlan",
    "build_plan",
    "render_plan",
    "render_undo",
]
