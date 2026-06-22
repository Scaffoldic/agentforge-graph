"""ENH-021: workspace-driven build commands (`ckg build/index/embed --workspace`).

One manifest + one command builds every member with its resolved config
(ENH-022), honoring the embed toggle (ENH-023), preflighting all members up front
(ENH-026), and continuing past a failing member with a per-member report.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph import preflight as pf
from agentforge_graph.cli import main

# defaults: a fake embedder so no credentials are needed in tests
_WS = """
workspace: org
defaults:
  embed:
    driver: fake
    dim: 16
members:
  - name: {m1}
    repo: ./r1
  - name: {m2}
    repo: ./r2
"""


def _repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "a.py").write_text("def f():\n    return 1\n")


def _workspace(tmp_path: Path, body: str = _WS) -> Path:
    _repo(tmp_path / "r1")
    _repo(tmp_path / "r2")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(body.format(m1="r1", m2="r2"))
    return ws


def test_build_workspace_indexes_and_embeds_all(tmp_path: Path, capsys) -> None:
    ws = _workspace(tmp_path)
    rc = main(["build", "--workspace", str(ws)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "workspace org: 2 member(s)" in out
    # both members built with an embedded store
    assert (tmp_path / "r1" / ".ckg" / "graph.kuzu").exists()
    assert (tmp_path / "r2" / ".ckg" / "graph.kuzu").exists()
    assert out.count("embed ") >= 2  # both embedded (fake driver)


def test_index_workspace_no_embed(tmp_path: Path, capsys) -> None:
    ws = _workspace(tmp_path)
    assert main(["index", "--workspace", str(ws)]) == 0
    assert (tmp_path / "r1" / ".ckg" / "graph.kuzu").exists()
    assert (tmp_path / "r2" / ".ckg" / "graph.kuzu").exists()
    out = capsys.readouterr().out
    assert "index " in out and "embed" not in out  # indexed only, no embed step


def test_embed_toggle_per_member(tmp_path: Path, capsys) -> None:
    _repo(tmp_path / "r1")
    _repo(tmp_path / "r2")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        """
workspace: org
defaults:
  embed:
    driver: fake
    dim: 16
members:
  - name: r1
    repo: ./r1
  - name: r2
    repo: ./r2
    embed: false
"""
    )
    assert main(["build", "--workspace", str(ws)]) == 0
    out = capsys.readouterr().out
    assert "embed disabled" in out  # r2 turned embedding off


def test_continue_on_error_reports_and_exits_nonzero(tmp_path: Path, capsys) -> None:
    _repo(tmp_path / "r1")
    _repo(tmp_path / "r2")
    # r2 selects an unknown embedder → it fails at the embed step; r1 still builds.
    # (Unknown driver names aren't a "missing extra", so preflight passes; the
    # failure surfaces during the run and is reported per-member.)
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        """
workspace: org
defaults:
  embed:
    driver: fake
    dim: 16
members:
  - name: r1
    repo: ./r1
  - name: bad
    repo: ./r2
    embed:
      driver: no-such-driver
"""
    )
    rc = main(["build", "--workspace", str(ws)])
    assert rc == 1  # a member failed
    out = capsys.readouterr().out
    assert "FAILED" in out
    assert (tmp_path / "r1" / ".ckg" / "graph.kuzu").exists()  # the healthy member still built


def test_preflight_blocks_whole_workspace_before_work(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(pf, "_module_present", lambda _m: False)  # no extras installed
    _repo(tmp_path / "r1")
    _repo(tmp_path / "r2")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        """
workspace: org
defaults:
  embed:
    driver: bedrock
members:
  - name: r1
    repo: ./r1
  - name: r2
    repo: ./r2
"""
    )
    rc = main(["build", "--workspace", str(ws)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "pip install 'agentforge-graph[bedrock]'" in err
    assert not (tmp_path / "r1" / ".ckg").exists()  # refused before any work


def test_read_only_member_skipped(tmp_path: Path, capsys) -> None:
    _repo(tmp_path / "r1")
    _repo(tmp_path / "r2")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        """
workspace: org
defaults:
  embed:
    driver: fake
    dim: 16
members:
  - name: r1
    repo: ./r1
  - name: r2
    repo: ./r2
    store:
      read_only: true
"""
    )
    rc = main(["build", "--workspace", str(ws)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "skipped" in out and "read-only" in out
    assert not (tmp_path / "r2" / ".ckg").exists()  # consume-only member untouched


def test_single_repo_build(tmp_path: Path, capsys) -> None:
    _repo(tmp_path / "r1")
    (tmp_path / "r1" / "ckg.yaml").write_text("embed:\n  driver: fake\n  dim: 16\n")
    rc = main(["build", str(tmp_path / "r1")])
    assert rc == 0
    out = capsys.readouterr().out
    assert "index" in out and "embed" in out
