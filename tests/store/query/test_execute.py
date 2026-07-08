"""Unit tests for the pure bounded-execution policy (feat-015 chunk 2).

``pull_bounded`` is clock-injected and DB-free, so the row/expansion/timeout
matrix is tested with a scripted row source and a fake clock.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable

from agentforge_graph.store.query.capability import QuerySettings
from agentforge_graph.store.query.execute import pull_bounded


def _source(n: int) -> Callable[[], tuple[object, ...] | None]:
    rows = iter([(i,) for i in range(n)])
    return lambda: next(rows, None)


def _clock(ticks: list[float]) -> Callable[[], float]:
    seq = iter(ticks)
    last = [0.0]

    def now() -> float:
        with contextlib.suppress(StopIteration):
            last[0] = next(seq)
        return last[0]

    return now


def test_complete_result_not_truncated() -> None:
    res = pull_bounded(_source(3), QuerySettings(max_rows=10), effective_limit=10, now=lambda: 0.0)
    assert res.rows == [(0,), (1,), (2,)]
    assert not res.truncated and res.stopped_reason is None


def test_row_cap_truncates_and_trims() -> None:
    res = pull_bounded(_source(10), QuerySettings(max_rows=3), effective_limit=3, now=lambda: 0.0)
    assert res.rows == [(0,), (1,), (2,)]
    assert res.truncated and res.stopped_reason == "row_cap"


def test_expansion_cap_backstops_before_row_cap() -> None:
    res = pull_bounded(
        _source(10),
        QuerySettings(max_rows=100, max_expansions=2),
        effective_limit=100,
        now=lambda: 0.0,
    )
    assert res.rows == [(0,), (1,)]
    assert res.truncated and res.stopped_reason == "expansion_cap"


def test_timeout_returns_partial() -> None:
    # clock jumps past the deadline after two rows are pulled.
    now = _clock([0.0, 0.0, 0.001, 0.001, 10.0])
    res = pull_bounded(
        _source(100), QuerySettings(max_rows=100, timeout_ms=1000), effective_limit=100, now=now
    )
    assert res.truncated and res.stopped_reason == "timeout"
    assert len(res.rows) < 100
