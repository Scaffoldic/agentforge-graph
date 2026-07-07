"""feat-014: the load-bearing local/central guardrail."""

from __future__ import annotations

import pytest

from agentforge_graph.config import StoreConfig
from agentforge_graph.ingest.watch import WatchGuardError, ensure_watchable


def test_local_writable_store_ok() -> None:
    ensure_watchable(StoreConfig(), read_only=False)  # does not raise


def test_central_store_refused() -> None:
    cfg = StoreConfig(central_root="/srv/ckg")
    with pytest.raises(WatchGuardError, match="central"):
        ensure_watchable(cfg, read_only=False)


def test_read_only_config_refused() -> None:
    cfg = StoreConfig(read_only=True)
    with pytest.raises(WatchGuardError, match="read-only"):
        ensure_watchable(cfg, read_only=False)


def test_read_only_flag_refused() -> None:
    with pytest.raises(WatchGuardError, match="read-only"):
        ensure_watchable(StoreConfig(), read_only=True)


def test_central_takes_precedence_over_read_only() -> None:
    cfg = StoreConfig(central_root="/srv/ckg", read_only=True)
    with pytest.raises(WatchGuardError, match="central"):
        ensure_watchable(cfg, read_only=True)
