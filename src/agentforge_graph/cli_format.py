"""Reusable columnar output rendering for the CLI (feat-015).

Introduced for ``ckg query --graph`` but written as a standalone helper other
verbs can adopt later without a rewrite — not inline in the query handler. Two
formats: an aligned text table (human) and JSON rows (machine).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def render_table(columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> str:
    """A monospace, left-aligned table with a header underline. Empty result
    still prints the header so the shape is visible."""
    headers = list(columns)
    body = [[_cell(v) for v in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in body:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    lines = [
        "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)),
        "  ".join("-" * widths[i] for i in range(len(headers))),
    ]
    lines += ["  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)) for row in body]
    if not body:
        lines.append("(no rows)")
    return "\n".join(lines)


def render_json(
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    truncated: bool = False,
    stopped_reason: str | None = None,
) -> str:
    """JSON with the column order, row arrays, and the truncation envelope."""
    payload = {
        "columns": list(columns),
        "rows": [list(row) for row in rows],
        "truncated": truncated,
        "stopped_reason": stopped_reason,
    }
    return json.dumps(payload, indent=2, default=str)
