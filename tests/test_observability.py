"""Engine logging (observability): level resolution, configure vs.
configure_from_config, the `logging:` config block, and an end-to-end CLI trace.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

from agentforge_graph import observability as obs
from agentforge_graph.cli import main
from agentforge_graph.config import LoggingConfig, ResolvedConfig


@pytest.fixture(autouse=True)
def _reset_root_logger() -> Iterator[None]:
    """Save/restore the shared `agentforge_graph` logger so tests don't leak
    level/handler state into each other."""
    lg = logging.getLogger(obs.ROOT)
    level, handlers = lg.level, lg.handlers[:]
    try:
        yield
    finally:
        lg.setLevel(level)
        lg.handlers[:] = handlers


# --- level resolution -------------------------------------------------------


def test_resolve_level_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CKG_LOG_LEVEL", raising=False)
    assert obs.resolve_level() == "warning"  # default
    assert obs.resolve_level(config_level="info") == "info"  # config over default
    monkeypatch.setenv("CKG_LOG_LEVEL", "error")
    assert obs.resolve_level(config_level="info") == "error"  # env over config
    assert obs.resolve_level(cli_verbose=True, config_level="info") == "info"  # -v over env
    assert obs.resolve_level(cli_debug=True, cli_verbose=True) == "debug"  # --debug over -v
    assert obs.resolve_level(cli_level="warning", cli_debug=True) == "warning"  # explicit wins


# --- configure / configure_from_config --------------------------------------


def test_configure_sets_level_and_handler() -> None:
    obs.configure("debug")
    lg = logging.getLogger(obs.ROOT)
    assert lg.level == logging.DEBUG
    assert lg.handlers  # a stderr handler was added
    n = len(lg.handlers)
    obs.configure("info")  # idempotent — no duplicate handler, level updated
    assert len(lg.handlers) == n
    assert lg.level == logging.INFO


def test_configure_from_config_only_when_unset() -> None:
    lg = logging.getLogger(obs.ROOT)
    lg.handlers[:] = []
    lg.setLevel(logging.NOTSET)
    obs.configure_from_config(ResolvedConfig(section={"logging": {"level": "debug"}}))
    assert lg.level == logging.DEBUG
    # already configured → a second call does not override
    obs.configure_from_config(ResolvedConfig(section={"logging": {"level": "error"}}))
    assert lg.level == logging.DEBUG


# --- config block -----------------------------------------------------------


def test_logging_config_block(tmp_path: Path) -> None:
    assert LoggingConfig().level == "warning"  # quiet default
    cfg = tmp_path / "ckg.yaml"
    cfg.write_text("logging:\n  level: debug\n")
    assert LoggingConfig.load(cfg).level == "debug"


# --- end-to-end CLI trace ---------------------------------------------------


def test_cli_index_emits_info_trace(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "a.py").write_text("def f():\n    return 1\n")
    with caplog.at_level(logging.INFO, logger=obs.ROOT):
        assert main(["index", str(repo), "--log-level", "info"]) == 0
    msgs = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("index:") and "done" in m for m in msgs), msgs
