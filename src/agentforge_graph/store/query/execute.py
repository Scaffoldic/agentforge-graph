"""The shared bounded-execution driver (feat-015).

Guardrails are written **once** here and reused by every backend, so a bound is a
real, tested guarantee on all of them rather than "best-effort where the backend
happens to support it". A backend adapter supplies only its native "run this
compiled statement and yield rows" primitive; this module wraps it with:

- **row cap** — stop after ``max_rows`` (the compiler already pushed
  ``LIMIT max_rows + 1``; pulling one extra row is how truncation is detected);
- **expansion cap** — a hard ceiling on rows pulled from the cursor, independent
  of the pushed LIMIT: a backstop if a backend does not honour the row cap;
- **timeout** — a soft wall-clock deadline checked between rows (returns the
  partial result gathered so far), plus a hard ``asyncio.wait_for`` backstop that
  raises ``GuardrailError`` if a single fetch hangs past the budget.

``pull_bounded`` is pure and clock-injected, so the whole policy is unit-tested
with a scripted row source and a fake clock — no database, no sleeps.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from .capability import QuerySettings
from .errors import GuardrailError

# Extra wall-clock grace for the hard asyncio backstop over the soft in-loop
# deadline, so the soft deadline (which yields a partial result) normally wins.
_HARD_TIMEOUT_GRACE_S = 2.0

Row = tuple[Any, ...]


@dataclass(frozen=True)
class BoundedResult:
    rows: list[Row]
    truncated: bool
    stopped_reason: str | None  # None | "row_cap" | "expansion_cap" | "timeout"


def pull_bounded(
    next_row: Callable[[], Row | None],
    settings: QuerySettings,
    effective_limit: int,
    now: Callable[[], float] = time.monotonic,
) -> BoundedResult:
    """Pull rows from ``next_row`` (returns ``None`` when exhausted) under the
    row/expansion/timeout bounds. Pure; ``now`` is injected for tests."""
    deadline = now() + settings.timeout_ms / 1000
    rows: list[Row] = []
    reason: str | None = None
    while True:
        if now() >= deadline:
            reason = "timeout"
            break
        if len(rows) >= settings.max_expansions:
            reason = "expansion_cap"
            break
        row = next_row()
        if row is None:
            break
        rows.append(row)
        if len(rows) > effective_limit:
            reason = "row_cap"
            rows = rows[:effective_limit]
            break
    return BoundedResult(rows=rows, truncated=reason is not None, stopped_reason=reason)


async def run_bounded(
    make_source: Callable[[], Iterator[Row]],
    settings: QuerySettings,
    effective_limit: int,
    now: Callable[[], float] = time.monotonic,
) -> BoundedResult:
    """Run ``make_source`` (which executes the statement and returns a row
    iterator) on a worker thread under the bounds. The DB work and the pull
    happen on one thread, so a non-thread-safe connection stays serial."""

    def work() -> BoundedResult:
        source = make_source()
        return pull_bounded(lambda: next(source, None), settings, effective_limit, now)

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(work),
            timeout=settings.timeout_ms / 1000 + _HARD_TIMEOUT_GRACE_S,
        )
    except TimeoutError as exc:  # a single fetch hung past the hard backstop
        raise GuardrailError(f"query exceeded the {settings.timeout_ms}ms time budget") from exc
