"""Engine logging — one ``agentforge_graph`` logger namespace consumers can dial
up to *info* or *debug* to trace a run end to end.

Control precedence (highest first): ``--log-level`` / ``--debug`` / ``-v`` on the
CLI → ``$CKG_LOG_LEVEL`` → ``logging.level`` in ckg.yaml → ``warning`` (quiet by
default). The CLI calls :func:`configure` (adds a stderr handler); the in-process
library path calls :func:`configure_from_config` (sets the level only, so it never
hijacks an app's own logging).

Framework-free (stdlib ``logging`` only, ADR-0001). Modules log via
``logging.getLogger(__name__)`` — no per-module setup.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentforge_graph.config import ConfigSource

ROOT = "agentforge_graph"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}


def _coerce(level: str | int | None) -> int:
    if isinstance(level, int):
        return level
    if not level:
        return logging.WARNING
    return _LEVELS.get(str(level).strip().lower(), logging.WARNING)


def configure(level: str | int | None = None) -> None:
    """Full CLI-side setup: a stderr handler on the ``agentforge_graph`` logger at
    ``level``. Idempotent — re-running just updates the level. Leaves propagation
    on so test/host log capture still sees the records."""
    logger = logging.getLogger(ROOT)
    logger.setLevel(_coerce(level))
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)


def resolve_level(
    *,
    cli_level: str | None = None,
    cli_debug: bool = False,
    cli_verbose: bool = False,
    config_level: str | None = None,
) -> str:
    """The effective level name from the precedence chain (flags → env → config →
    ``warning``)."""
    if cli_level:
        return cli_level
    if cli_debug:
        return "debug"
    if cli_verbose:
        return "info"
    env = os.environ.get("CKG_LOG_LEVEL")
    if env:
        return env
    return config_level or "warning"


def configure_from_config(config: ConfigSource) -> None:
    """In-process (library) path: set the namespace level from ``logging.level``
    in ``config`` **iff** logging isn't already configured (by the CLI or the
    host app). Adds no handler, so an app's own logging setup is respected."""
    logger = logging.getLogger(ROOT)
    if logger.level != logging.NOTSET:  # already configured — don't override
        return
    from agentforge_graph.config import LoggingConfig

    logger.setLevel(_coerce(LoggingConfig.load(config).level))
