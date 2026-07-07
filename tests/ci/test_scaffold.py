"""feat-014: ckg ci init — workflow rendering + managed-marker discipline."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentforge_graph.ci import (
    MARKER,
    WORKFLOW_REL_PATH,
    CiInitError,
    render_workflow,
    scaffold_workflow,
)


def test_render_has_marker_and_single_writer() -> None:
    wf = render_workflow()
    assert wf.startswith(MARKER)
    assert "concurrency:" in wf
    assert "group: ckg-central-index" in wf
    assert "branches: [main]" in wf
    assert "ckg index ." in wf
    assert "ckg embed ." in wf  # embed on by default


def test_render_full_mode_and_no_embed() -> None:
    wf = render_workflow(mode="full", embed=False)
    assert "ckg index . --full" in wf
    assert "ckg embed ." not in wf


def test_render_extras_and_enrich() -> None:
    wf = render_workflow(extras=["bedrock"], enrich=True)
    assert 'pip install "agentforge-graph[bedrock]"' in wf
    assert "ckg enrich ." in wf


def test_render_rejects_bad_mode() -> None:
    with pytest.raises(ValueError):
        render_workflow(mode="sideways")


def test_creates_workflow_file(tmp_path: Path) -> None:
    res = scaffold_workflow(tmp_path)
    assert res.action == "created"
    assert res.path == tmp_path / WORKFLOW_REL_PATH
    assert res.path.read_text().startswith(MARKER)


def test_idempotent_noop(tmp_path: Path) -> None:
    scaffold_workflow(tmp_path)
    res = scaffold_workflow(tmp_path)
    assert res.action == "noop"


def test_update_when_options_change(tmp_path: Path) -> None:
    scaffold_workflow(tmp_path, mode="incremental")
    res = scaffold_workflow(tmp_path, mode="full")
    assert res.action == "updated"
    assert "ckg index . --full" in res.path.read_text()


def test_refuses_to_clobber_unmanaged(tmp_path: Path) -> None:
    target = tmp_path / WORKFLOW_REL_PATH
    target.parent.mkdir(parents=True)
    target.write_text("name: my hand-written workflow\n")
    with pytest.raises(CiInitError, match="not managed"):
        scaffold_workflow(tmp_path)


def test_force_overwrites_unmanaged(tmp_path: Path) -> None:
    target = tmp_path / WORKFLOW_REL_PATH
    target.parent.mkdir(parents=True)
    target.write_text("name: my hand-written workflow\n")
    res = scaffold_workflow(tmp_path, force=True)
    assert res.action == "overwritten"
    assert res.path.read_text().startswith(MARKER)


def test_print_only_writes_nothing(tmp_path: Path) -> None:
    res = scaffold_workflow(tmp_path, print_only=True)
    assert res.action == "printed"
    assert not (tmp_path / WORKFLOW_REL_PATH).exists()


def test_unknown_provider(tmp_path: Path) -> None:
    with pytest.raises(CiInitError, match="unknown CI provider"):
        scaffold_workflow(tmp_path, provider="jenkins")
