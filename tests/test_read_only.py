"""ENH-018: read-only consumers.

A consume-only store (``store.read_only`` / ``--read-only`` / ``$CKG_READ_ONLY``)
refuses the write verbs and never creates a missing index, while read verbs work
normally. This is what lets a team host one index and hand it to many consumers.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agentforge_graph.cli import main
from agentforge_graph.config import StoreConfig
from agentforge_graph.store import is_read_only
from agentforge_graph.store.errors import StoreError
from agentforge_graph.store.facade import _check_or_init_meta


@pytest.fixture(autouse=True)
def _clean_env() -> None:
    # main() bridges --read-only to the process env; keep tests isolated
    os.environ.pop("CKG_READ_ONLY", None)
    yield
    os.environ.pop("CKG_READ_ONLY", None)


# --- is_read_only ----------------------------------------------------------


def test_is_read_only_from_config() -> None:
    assert is_read_only(StoreConfig(read_only=True))


def test_is_read_only_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CKG_READ_ONLY", "1")
    assert is_read_only(StoreConfig())


def test_is_read_only_default_false() -> None:
    assert not is_read_only(StoreConfig())


# --- facade: missing index under read-only errors, never creates ------------


def test_check_meta_read_only_missing_raises(tmp_path: Path) -> None:
    target = tmp_path / "nope"
    with pytest.raises(StoreError):
        _check_or_init_meta(target, read_only=True)
    assert not target.exists()  # did not create the index dir


def test_check_meta_writable_missing_creates(tmp_path: Path) -> None:
    target = tmp_path / "fresh"
    _check_or_init_meta(target, read_only=False)
    assert (target / "meta.json").exists()


# --- CLI: write verbs refuse, read verbs work -------------------------------


def test_flag_refuses_write_verb(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    code = main(["index", str(repo), "--read-only"])
    assert code == 2
    assert "read-only" in capsys.readouterr().err.lower()


def test_config_read_only_refuses_write_verb(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "ckg.yaml").write_text("store:\n  read_only: true\n")
    assert main(["index", str(repo)]) == 2
    assert main(["embed", str(repo)]) == 2
    assert main(["enrich", str(repo)]) == 2


def test_read_only_consumer_reads_but_cannot_write(tmp_path: Path) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n")
    # build the index while writable (each main() owns its own event loop)
    assert main(["index", str(repo)]) == 0
    # now consume read-only: status reads fine, index refuses
    assert main(["status", str(repo), "--read-only"]) == 0
    assert main(["index", str(repo), "--read-only"]) == 2
