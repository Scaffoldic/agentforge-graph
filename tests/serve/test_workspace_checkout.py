"""ENH-024: remote repo sources — a workspace member named by a git URL is
cloned into a managed checkout and built. Tests use a local git repo as the
"remote", so CI needs no network.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.serve.checkout import ensure_checkout
from agentforge_graph.serve.workspace import WorkspaceConfig, WorkspaceMember


def _git_repo(path: Path, *, content: str = "def f():\n    return 1\n") -> Path:
    """A real git repo with one commit — stands in for a remote to clone."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    (path / "a.py").write_text(content)
    subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
    ident = ["-c", "user.email=t@t", "-c", "user.name=t"]
    subprocess.run(["git", "-C", str(path), *ident, "commit", "-q", "-m", "init"], check=True)
    return path


# --- member validation ------------------------------------------------------


def test_member_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        WorkspaceMember(name="x", repo="./a", git="git@h:o/r.git")
    with pytest.raises(ValueError, match="exactly one"):
        WorkspaceMember(name="x")
    # one or the other is fine
    assert WorkspaceMember(name="x", repo="./a").repo == "./a"
    assert WorkspaceMember(name="y", git="git@h:o/r.git").git == "git@h:o/r.git"


def test_member_repo_for_git_is_under_checkouts(tmp_path: Path) -> None:
    ws = tmp_path / "workspace.yaml"
    ws.write_text("members:\n  - name: gw\n    git: git@github.com:acme/gateway.git\n")
    cfg = WorkspaceConfig.load(ws)
    repo = cfg.member_repo(cfg.members[0])
    assert repo == tmp_path / ".checkouts" / "acme-gateway"


# --- ensure_checkout --------------------------------------------------------


def test_ensure_checkout_clones_then_is_idempotent(tmp_path: Path) -> None:
    src = _git_repo(tmp_path / "src")
    dest = tmp_path / ".checkouts" / "src"
    ensure_checkout(str(src), dest)
    assert (dest / "a.py").exists()
    assert (tmp_path / ".checkouts" / ".gitignore").read_text() == "*\n"
    # second call (fetch + ff) is a no-op that still leaves a valid checkout
    ensure_checkout(str(src), dest)
    assert (dest / "a.py").exists()


def test_ensure_checkout_pins_ref(tmp_path: Path) -> None:
    src = _git_repo(tmp_path / "src")
    subprocess.run(["git", "-C", str(src), "tag", "v1"], check=True)
    dest = tmp_path / ".checkouts" / "src"
    ensure_checkout(str(src), dest, ref="v1")
    head = subprocess.run(
        ["git", "-C", str(dest), "describe", "--tags"], capture_output=True, text=True, check=True
    )
    assert head.stdout.strip() == "v1"


# --- end-to-end build of a git member ---------------------------------------


def test_build_workspace_with_git_member(tmp_path: Path, capsys) -> None:
    src = _git_repo(tmp_path / "remote")
    ws = tmp_path / "workspace.yaml"
    ws.write_text(
        f"""
workspace: org
defaults:
  embed:
    driver: fake
    dim: 16
members:
  - name: gateway
    git: {src}
"""
    )
    rc = main(["build", "--workspace", str(ws)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "gateway" in out
    # cloned into the managed checkout and indexed there
    checkout = tmp_path / ".checkouts"
    assert (checkout / ".gitignore").exists()
    built = next(checkout.glob("*/.ckg/graph.kuzu"), None)
    assert built is not None, "git member was cloned and indexed"
