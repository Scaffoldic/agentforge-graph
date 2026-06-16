"""feat-009 chunk 1 — lifecycle recording through the real index/refresh path.

A full index seeds OPENED for every symbol at the index commit; an incremental
refresh CLOSES symbols that vanished and OPENS ones that appeared, stamped at the
new commit. Temporal OFF (default) records nothing and leaves no sidecar.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentforge_graph.core import SymbolID
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.temporal import EventKind, TemporalStore

_CFG_ON = "store:\n  path: .ckg\ntemporal:\n  enabled: true\n"
_CFG_OFF = "store:\n  path: .ckg\ntemporal:\n  enabled: false\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _commit(repo: Path, msg: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")


def _descriptors(events) -> dict:  # type: ignore[no-untyped-def]
    """{descriptor: set(event kinds)} — descriptor is the symbol id's last field."""
    out: dict[str, set] = {}
    for e in events:
        d = SymbolID.parse(e.symbol_id).descriptor
        out.setdefault(d, set()).add(e.event)
    return out


async def test_full_then_incremental_lifecycle(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG_ON)

    # S0: alpha + beta. Full index → both OPENED at commit0.
    (repo / "m.py").write_text("def alpha():\n    return 1\n\n\ndef beta():\n    return 2\n")
    (repo / "gone.py").write_text("def doomed():\n    return 0\n")
    c0 = _commit(repo, "s0")
    cg = await CodeGraph.index(repo_path=repo, config=cfg)
    await cg.close()

    store = TemporalStore.open(repo / ".ckg")
    d0 = _descriptors(await store.all_events())
    assert d0.get("alpha().") == {EventKind.OPENED}
    assert d0.get("beta().") == {EventKind.OPENED}
    assert d0.get("doomed().") == {EventKind.OPENED}
    assert all(e.commit == c0 for e in await store.all_events())

    # S1: rename beta -> gamma (close beta, open gamma); delete gone.py.
    (repo / "m.py").write_text("def alpha():\n    return 1\n\n\ndef gamma():\n    return 3\n")
    (repo / "gone.py").unlink()
    c1 = _commit(repo, "s1")
    cg2 = await CodeGraph.index(repo_path=repo, config=cfg)  # incremental
    await cg2.close()

    d1 = _descriptors(await store.all_events())
    assert EventKind.CLOSED in d1["beta()."], "renamed-away symbol must close"
    assert EventKind.CLOSED in d1["doomed()."], "deleted-file symbol must close"
    assert d1.get("gamma().") == {EventKind.OPENED}, "new symbol must open"
    assert d1["alpha()."] == {EventKind.OPENED}, "unchanged symbol gets no new event"

    # the S1 events carry the new commit
    closes = [e for e in await store.all_events() if e.event is EventKind.CLOSED]
    assert closes and all(e.commit == c1 for e in closes)


async def test_temporal_off_writes_no_sidecar(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    _init_repo(repo)
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text(_CFG_OFF)
    (repo / "m.py").write_text("def alpha():\n    return 1\n")
    _commit(repo, "s0")
    cg = await CodeGraph.index(repo_path=repo, config=cfg)
    await cg.close()
    assert not (repo / ".ckg" / "temporal.db").exists()
