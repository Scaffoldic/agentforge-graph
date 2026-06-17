"""Churn / authorship mining (feat-009 chunk 2).

A symbol's *churn* and *authorship* are ranking + ownership signals
(design-009 §4.5): how much it has moved lately and who has been editing it.
We mine them from ``git log`` over a bounded window and attribute each diff
hunk to the symbol(s) whose **current span** overlaps the hunk's new-line
range. Attribution is approximate *by design* — historical line numbers drift
from current spans — which is fine for a ranking signal (it is never asserted
as provenance).

One batched ``git log -U0`` call per refresh covers all touched paths; the
window (default 90d, derived from the commit's author time so results are
deterministic in tests) bounds cost. Output is a small, bounded
``SymbolAggregate`` per symbol — never a per-commit fact (design §4.10).
"""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

_DAY = 86_400
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_SOH = "\x01"  # commit-header marker (unambiguous vs. patch text)


@dataclass(frozen=True)
class SymbolAggregate:
    """Bounded churn/authorship rollup for one symbol (design §4.4 aggregates)."""

    symbol_id: str
    churn_30d: int
    churn_90d: int
    top_authors: list[tuple[str, int]]  # (name, commits), ≤3, desc by commits
    introduced_sha: str
    introduced_ts: int
    last_changed_sha: str
    last_changed_ts: int

    def attrs(self) -> dict[str, object]:
        """The denormalised view written onto a node's ``attrs`` (design §4.0)
        so ``ckg_symbol`` surfaces it with no join."""
        return {
            "churn_30d": self.churn_30d,
            "churn_90d": self.churn_90d,
            "top_authors": [{"name": n, "commits": c} for n, c in self.top_authors],
            "introduced": self.introduced_sha,
            "introduced_ts": self.introduced_ts,
            "last_changed": self.last_changed_sha,
            "last_changed_ts": self.last_changed_ts,
        }


@dataclass
class _Acc:
    """Per-symbol accumulator while walking the log."""

    churn_30d: int = 0
    churn_90d: int = 0
    authors: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))  # name -> shas
    first: tuple[int, str] = (1 << 62, "")  # (ts, sha) oldest
    last: tuple[int, str] = (-1, "")  # (ts, sha) newest


class ChurnMiner:
    """Mines churn/authorship for a set of files over a commit-time window."""

    def __init__(self, repo_root: str, *, now_ts: int, window_days: int = 90) -> None:
        self._root = repo_root
        self._now = now_ts
        self._window = window_days

    def mine(
        self, spans_by_path: dict[str, list[tuple[str, tuple[int, int]]]]
    ) -> list[SymbolAggregate]:
        """Attribute windowed churn/authorship to the symbols in ``spans_by_path``
        (``path -> [(symbol_id, (start_line, end_line)), …]``)."""
        paths = [p for p, syms in spans_by_path.items() if syms]
        if not paths or self._now <= 0:
            return []
        log = self._git_log(paths)
        if log is None:
            return []
        acc: dict[str, _Acc] = defaultdict(_Acc)
        cut30 = self._now - 30 * _DAY
        cut90 = self._now - 90 * _DAY
        for sha, ts, author, path, new_start, count, delta in self._hunks(log):
            for sid in self._overlapping(spans_by_path.get(path, []), new_start, count):
                a = acc[sid]
                a.churn_90d += delta if ts >= cut90 else 0
                a.churn_30d += delta if ts >= cut30 else 0
                a.authors[author].add(sha)
                if ts < a.first[0]:
                    a.first = (ts, sha)
                if ts > a.last[0]:
                    a.last = (ts, sha)
        return [self._aggregate(sid, a) for sid, a in sorted(acc.items())]

    # --- internals --------------------------------------------------------

    def _git_log(self, paths: list[str]) -> str | None:
        since = datetime.fromtimestamp(max(self._now - self._window * _DAY, 0), tz=UTC).strftime(
            "%Y-%m-%d"
        )
        try:
            out = subprocess.run(
                [
                    "git",
                    "-C",
                    self._root,
                    "log",
                    "--no-renames",
                    "--no-color",
                    "-U0",
                    f"--since={since}",
                    f"--format={_SOH}%H%x09%ct%x09%an",
                    "--",
                    *paths,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        return out.stdout

    def _hunks(self, log: str):  # type: ignore[no-untyped-def]
        """Yield ``(sha, ts, author, path, new_start, line_count, churn_delta)`` per
        hunk. ``churn_delta`` = added + deleted lines for the hunk."""
        sha = author = path = ""
        ts = 0
        for line in log.splitlines():
            if line.startswith(_SOH):
                parts = line[1:].split("\t")
                if len(parts) == 3:
                    sha, ts_s, author = parts
                    ts = int(ts_s) if ts_s.isdigit() else 0
                path = ""
                continue
            if line.startswith("diff --git "):
                path = ""
                continue
            if line.startswith("+++ b/"):
                path = line[6:]
                continue
            if line.startswith("@@"):
                m = _HUNK.match(line)
                if not m or not path:
                    continue
                new_start = int(m.group(1))
                added = int(m.group(2)) if m.group(2) is not None else 1
                deleted = self._removed(line)
                yield sha, ts, author, path, new_start, added, added + deleted

    @staticmethod
    def _removed(hunk: str) -> int:
        m = re.match(r"^@@ -\d+(?:,(\d+))? \+", hunk)
        if not m:
            return 0
        return int(m.group(1)) if m.group(1) is not None else 1

    @staticmethod
    def _overlapping(
        syms: list[tuple[str, tuple[int, int]]], new_start: int, count: int
    ) -> list[str]:
        lo = new_start
        hi = new_start + max(count, 1) - 1
        return [sid for sid, (s, e) in syms if not (e < lo or s > hi)]

    def _aggregate(self, sid: str, a: _Acc) -> SymbolAggregate:
        top = sorted(
            ((name, len(shas)) for name, shas in a.authors.items()),
            key=lambda t: (-t[1], t[0]),
        )[:3]
        intro_ts, intro_sha = a.first if a.first[1] else (0, "")
        last_ts, last_sha = a.last if a.last[1] else (0, "")
        return SymbolAggregate(
            symbol_id=sid,
            churn_30d=a.churn_30d,
            churn_90d=a.churn_90d,
            top_authors=top,
            introduced_sha=intro_sha,
            introduced_ts=intro_ts,
            last_changed_sha=last_sha,
            last_changed_ts=last_ts,
        )
