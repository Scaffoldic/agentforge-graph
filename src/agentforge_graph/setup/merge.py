"""Structural MCP-config merge for ``ckg setup`` (feat-013, chunk 2).

Both the repo-root ``.mcp.json`` (project scope) and ``~/.claude.json`` (user
scope) are JSON objects holding an ``mcpServers`` map, so one merger serves
both. The rules that make editing files the user didn't author *safe*:

- **Structural, never textual.** Parse → set our ``mcpServers.ckg`` key →
  serialize. Unrelated servers and keys are preserved.
- **Marker-scoped.** Our entry carries ``_managed_by: agentforge-graph``. We
  only ever replace/remove an entry that carries it — a user's own ``ckg``
  entry is a *conflict*, never silently clobbered (unless ``--force``).
- **Idempotent.** Writing twice yields a byte-identical file (status ``noop``).
- **Reversible.** ``undo`` removes exactly our marked entry, and deletes a file
  that becomes empty because it only held our entry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .errors import SetupError

MARKER_KEY = "_managed_by"
MARKER_VALUE = "agentforge-graph"
SERVER_NAME = "ckg"
_LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_transport(transport: str, host: str, token: str) -> None:
    """ENH-005 bind-safety, carried into generated config: refuse to write an
    HTTP entry bound to a non-loopback host without an auth token."""
    if transport == "http" and host not in _LOOPBACK and not token:
        raise SetupError(
            f"refusing to write an http MCP entry bound to non-loopback host {host!r} "
            "without an auth token (ENH-005 bind-safety) — pass a token or use a "
            "loopback host"
        )


def build_entry(
    repo_arg: str,
    *,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    token: str = "",
) -> dict[str, object]:
    """The MCP server entry for the chosen transport, marker included."""
    validate_transport(transport, host, token)
    if transport == "http":
        return {"url": f"http://{host}:{port}/mcp", MARKER_KEY: MARKER_VALUE}
    return {
        "command": "ckg",
        "args": ["serve-mcp", "--repo", repo_arg],
        MARKER_KEY: MARKER_VALUE,
    }


def _is_ours(entry: object) -> bool:
    return isinstance(entry, dict) and entry.get(MARKER_KEY) == MARKER_VALUE


def _serialize(doc: dict[str, object]) -> str:
    return json.dumps(doc, indent=2) + "\n"


def load(path: Path) -> dict[str, object] | None:
    """Parse an existing JSON config, or ``None`` if absent. Raises
    :class:`SetupError` on unreadable / non-object JSON (never a stack trace)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SetupError(f"{path} is not a JSON object")
    return data


@dataclass(frozen=True)
class Outcome:
    status: str  # create | update | noop | conflict
    doc: dict[str, object] | None  # the document to write (None ⇒ nothing to write)


def plan_entry(
    existing: dict[str, object] | None,
    entry: dict[str, object],
    *,
    server: str = SERVER_NAME,
    force: bool = False,
) -> Outcome:
    """Pure planning: what writing ``entry`` into ``existing`` would do.

    ``create`` (no prior server / new file) · ``update`` (replace our prior
    entry) · ``noop`` (identical) · ``conflict`` (a user-authored entry of the
    same name; refused unless ``force``)."""
    doc: dict[str, object] = dict(existing) if existing is not None else {}
    raw = doc.get("mcpServers")
    servers: dict[str, object] = dict(raw) if isinstance(raw, dict) else {}
    cur = servers.get(server)

    if cur is not None and not _is_ours(cur) and not force:
        return Outcome("conflict", None)
    if cur == entry:
        return Outcome("noop", None)

    servers[server] = entry
    doc["mcpServers"] = servers
    return Outcome("create" if cur is None else "update", doc)


def write_entry(path: Path, entry: dict[str, object], *, force: bool = False) -> str:
    """Apply ``entry`` to ``path`` structurally. Returns the status; raises
    :class:`SetupError` on a conflict."""
    outcome = plan_entry(load(path), entry, force=force)
    if outcome.status == "conflict":
        raise SetupError(
            f"{path} already has a '{SERVER_NAME}' MCP server you authored; "
            "remove it or re-run with --force"
        )
    if outcome.doc is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize(outcome.doc))
    return outcome.status


def undo_entry(path: Path, *, server: str = SERVER_NAME) -> str:
    """Remove our marked entry from ``path``. Returns ``absent`` (no file),
    ``skipped`` (no entry of ours), ``removed`` (entry deleted, file kept), or
    ``removed-file`` (file deleted because it held only our entry)."""
    existing = load(path)
    if existing is None:
        return "absent"
    raw = existing.get("mcpServers")
    servers: dict[str, object] = dict(raw) if isinstance(raw, dict) else {}
    cur = servers.get(server)
    if cur is None or not _is_ours(cur):
        return "skipped"

    del servers[server]
    rest = {k: v for k, v in existing.items() if k != "mcpServers"}
    if servers:
        existing["mcpServers"] = servers
        path.write_text(_serialize(existing))
        return "removed"
    if rest:  # other top-level keys remain — drop mcpServers, keep them
        path.write_text(_serialize(rest))
        return "removed"
    # The file held nothing but our entry → remove it.
    path.unlink()
    return "removed-file"
