"""ENH-018: store-location resolution — in-repo vs. central root.

Locks the developer choice: the default stays the repo-relative ``.ckg``
(byte-for-byte today's behavior), while a configured ``central_root`` routes
each repo to a stable, collision-free per-repo subdir — so a team/CI can host
many repos' indexes in one place.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from agentforge_graph.config import StoreConfig
from agentforge_graph.ingest import CodeGraph
from agentforge_graph.store.location import repo_key, resolve_root


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


# --- resolve_root ----------------------------------------------------------


def test_in_repo_default_unchanged(tmp_path: Path) -> None:
    # central_root unset → repo_path/.ckg, exactly as before ENH-018
    assert resolve_root(tmp_path, StoreConfig()) == tmp_path / ".ckg"


def test_absolute_store_path_still_honored(tmp_path: Path) -> None:
    # the pre-ENH-018 "absolute store.path escapes the repo" behavior is preserved
    elsewhere = tmp_path / "elsewhere"
    assert resolve_root(tmp_path, StoreConfig(path=str(elsewhere))) == elsewhere


def test_central_root_uses_per_repo_subdir(tmp_path: Path) -> None:
    central = tmp_path / "central"
    repo = tmp_path / "repo"
    repo.mkdir()
    root = resolve_root(repo, StoreConfig(central_root=str(central)))
    assert root.parent == central
    assert root == central / repo_key(repo)


def test_central_root_no_collision_between_repos(tmp_path: Path) -> None:
    central = tmp_path / "central"
    (a := tmp_path / "a").mkdir()
    (b := tmp_path / "b").mkdir()
    cfg = StoreConfig(central_root=str(central))
    assert resolve_root(a, cfg) != resolve_root(b, cfg)


def test_central_root_expanduser(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    root = resolve_root(tmp_path / "repo", StoreConfig(central_root="~/ckg"))
    assert str(root).startswith(str(tmp_path / "ckg"))


# --- repo_key --------------------------------------------------------------


def test_repo_key_from_ssh_remote(tmp_path: Path) -> None:
    repo = tmp_path / "myrepo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "remote", "add", "origin", "git@github.com:Scaffoldic/agentforge-graph.git")
    assert repo_key(repo) == "Scaffoldic-agentforge-graph"


def test_repo_key_from_https_remote(tmp_path: Path) -> None:
    repo = tmp_path / "r2"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "remote", "add", "origin", "https://github.com/acme/orders.git")
    assert repo_key(repo) == "acme-orders"


def test_repo_key_without_remote_is_stable_and_path_based(tmp_path: Path) -> None:
    repo = tmp_path / "lonely"
    repo.mkdir()  # no git remote
    key = repo_key(repo)
    assert key == repo_key(repo)  # stable across calls
    assert key.startswith("lonely-")  # dirname prefix + path hash
    (other := tmp_path / "lonely2").mkdir()
    assert repo_key(other) != key  # a different path keys differently


# --- integration: artifacts actually land centrally ------------------------


async def test_index_writes_to_central_root_not_the_repo(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n")
    central = tmp_path / "central"
    cfg_path = tmp_path / "ckg.yaml"
    cfg_path.write_text(f"store:\n  central_root: {central}\n")

    cg = await CodeGraph.index(repo_path=repo, config=cfg_path)
    await cg.close()

    sub = central / repo_key(repo)
    assert (sub / "meta.json").exists()  # the index landed centrally
    assert not (repo / ".ckg").exists()  # and NOT in the repo working copy
