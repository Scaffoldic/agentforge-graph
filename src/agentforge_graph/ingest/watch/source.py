"""feat-014: the ``watchfiles``-backed event source (the only place that touches
the fs-watch dependency).

Lazy-imports ``watchfiles`` so the base install stays lean; a missing dep is a
clear ``pip install agentforge-graph[watch]`` hint, not a traceback. Converts the
raw change stream into the single-event ``pull(timeout)`` shape ``WatchRunner``
consumes: an :class:`Event`, or ``None`` when the timeout elapsed with no event.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

from .filter import WatchFilter
from .policy import Event

_INSTALL_HINT = (
    "ckg watch needs the 'watch' extra. Install it with:\n"
    "  pip install 'agentforge-graph[watch]'   (or: uv sync --extra watch)"
)


def _import_watchfiles() -> object:
    try:
        import watchfiles  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised via the CLI hint
        raise WatchDependencyError(_INSTALL_HINT) from exc
    return watchfiles


class WatchDependencyError(Exception):
    """The optional ``watchfiles`` dependency is not installed."""


class WatchfilesSource:
    """Runs ``watchfiles.awatch`` in a background task, classifying each change
    into an :class:`Event` and enqueuing it for :meth:`pull`."""

    def __init__(self, root: str | Path, wfilter: WatchFilter) -> None:
        self.root = str(Path(root).resolve())
        self.filter = wfilter
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        wf = _import_watchfiles()
        awatch = wf.awatch  # type: ignore[attr-defined]

        def _keep(_change: object, path: str) -> bool:
            rel = self.filter.relative(self.root, path)
            return rel is not None and self.filter.keep(rel)

        async def _consume() -> None:
            async for changes in awatch(self.root, watch_filter=_keep):
                for _change, path in changes:
                    rel = self.filter.relative(self.root, path)
                    if rel is None:
                        continue
                    ev = self.filter.classify(rel)
                    if ev is not None:
                        self._queue.put_nowait(ev)

        self._task = asyncio.ensure_future(_consume())

    async def pull(self, timeout: float | None) -> Event | None:
        try:
            return await asyncio.wait_for(self._queue.get(), timeout)
        except TimeoutError:
            return None

    async def aclose(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
