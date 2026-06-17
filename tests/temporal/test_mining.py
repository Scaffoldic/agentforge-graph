"""feat-009 chunk 2 — churn/authorship attribution math (``ChurnMiner``).

A scripted git repo with two functions edited by two authors over four commits;
the miner must attribute each diff hunk to the symbol whose span it overlaps,
sum the churn, count authors, and pin introduced/last-changed to the right
commits.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from agentforge_graph.temporal.mining import ChurnMiner

# final file layout (the *current* spans the miner attributes against):
#   1 def alpha():        ┐
#   2     x = 1           │ alpha → (1, 3)
#   3     return x        ┘
#   4
#   5 def beta():         ┐
#   6     y = 2           │ beta → (5, 8)
#   7     z = 3           │
#   8     return y + z    ┘
ALPHA = ("alpha", (1, 3))
BETA = ("beta", (5, 8))


def _run(repo: Path, *args: str, author: str | None = None, ts: int | None = None) -> str:
    env = dict(os.environ)
    if author:
        env |= {
            "GIT_AUTHOR_NAME": author, "GIT_AUTHOR_EMAIL": f"{author}@t",
            "GIT_COMMITTER_NAME": author, "GIT_COMMITTER_EMAIL": f"{author}@t",
        }
    if ts is not None:  # pin distinct commit times so introduced/last ordering is exact
        env |= {"GIT_AUTHOR_DATE": f"{ts} +0000", "GIT_COMMITTER_DATE": f"{ts} +0000"}
    out = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    )
    return out.stdout.strip()


# four commits an hour apart, ending "now-ish" so they fall inside the window.
_BASE_TS = 1_750_000_000  # 2025-06-15, well within a 90-day window of itself


def _commit(repo: Path, author: str, msg: str, ts: int) -> str:
    _run(repo, "add", "-A")
    _run(repo, "commit", "-m", msg, author=author, ts=ts)
    return _run(repo, "rev-parse", "HEAD")


def _now_ts(repo: Path) -> int:
    return int(_run(repo, "show", "-s", "--format=%ct", "HEAD"))


def _build_repo(repo: Path) -> dict[str, str]:
    repo.mkdir(parents=True)
    _run(repo, "init")
    m = repo / "m.py"
    # c0 (Ann): alpha + trailing blank → lines 1-4
    alpha = "def alpha():\n    x = 1\n    return x\n\n"
    beta = "def beta():\n    y = 2\n    z = 3\n    return y + z\n"
    m.write_text(alpha)
    c0 = _commit(repo, "Ann", "c0 add alpha", _BASE_TS)
    # c1 (Bob): append beta → lines 5-8
    m.write_text(alpha + beta)
    c1 = _commit(repo, "Bob", "c1 add beta", _BASE_TS + 3600)
    # c2 (Ann): edit alpha line 2 in place
    m.write_text(alpha.replace("x = 1", "x = 9") + beta)
    c2 = _commit(repo, "Ann", "c2 edit alpha", _BASE_TS + 7200)
    # c3 (Bob): edit beta line 6 in place
    m.write_text(alpha.replace("x = 1", "x = 9") + beta.replace("y = 2", "y = 8"))
    c3 = _commit(repo, "Bob", "c3 edit beta", _BASE_TS + 10800)
    return {"c0": c0, "c1": c1, "c2": c2, "c3": c3}


def test_attribution_by_span_overlap(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    shas = _build_repo(repo)
    spans = {"m.py": [ALPHA, BETA]}
    aggs = {a.symbol_id: a for a in ChurnMiner(str(repo), now_ts=_now_ts(repo)).mine(spans)}

    alpha, beta = aggs["alpha"], aggs["beta"]

    # each function's edits land on the right symbol (no cross-attribution)
    assert dict(alpha.top_authors) == {"Ann": 2}
    assert dict(beta.top_authors) == {"Bob": 2}

    # introduced = first commit touching the span; last_changed = most recent
    assert alpha.introduced_sha == shas["c0"]
    assert alpha.last_changed_sha == shas["c2"]
    assert beta.introduced_sha == shas["c1"]
    assert beta.last_changed_sha == shas["c3"]

    # churn = summed added+deleted of overlapping hunks (add 1-4=4 then ±1=2)
    assert alpha.churn_90d == 6
    assert beta.churn_90d == 6
    assert alpha.last_changed_ts > 0


def test_same_day_commits_count_in_both_windows(tmp_path: Path) -> None:
    """All fixture commits are recent, so 30d and 90d churn coincide."""
    repo = tmp_path / "proj"
    _build_repo(repo)
    spans = {"m.py": [ALPHA, BETA]}
    aggs = {a.symbol_id: a for a in ChurnMiner(str(repo), now_ts=_now_ts(repo)).mine(spans)}
    for agg in aggs.values():
        assert agg.churn_30d == agg.churn_90d
        assert len(agg.top_authors) <= 3


def test_no_paths_is_empty(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _build_repo(repo)
    assert ChurnMiner(str(repo), now_ts=_now_ts(repo)).mine({}) == []
    assert ChurnMiner(str(repo), now_ts=0).mine({"m.py": [ALPHA]}) == []
