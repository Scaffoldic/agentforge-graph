"""ENH-026: fail-fast config preflight.

Validate the consumer's *resolved* config **before** any indexing/embedding work:
is the selected driver's optional dependency installed, and are the required
credentials present? Surface the exact fix (``pip install
'agentforge-graph[bedrock]'``) instead of a raw ``ModuleNotFoundError`` thrown
deep inside a run.

Probes are import-light — :func:`importlib.util.find_spec` and env-var presence,
never a live model call — so the gate is cheap and deterministic. A live
connectivity check is a separate, opt-in concern.

Engine-shared and deterministic: must not import ``agentforge`` (ADR-0001).
"""

from __future__ import annotations

import importlib.util
import os
from dataclasses import dataclass

from agentforge_graph.config import ConfigSource, EmbedConfig, EnrichConfig, StoreConfig

PACKAGE = "agentforge-graph"

# Driver/provider name → (probe import module, pip extra). A driver absent from
# this table ships in the base install and needs no extra (fake/scripted/kuzu/
# lancedb/anthropic). One source of truth for both the preflight and the live
# builders' in-process guard.
_REQUIREMENTS: dict[str, tuple[str, str]] = {
    "bedrock": ("boto3", "bedrock"),
    "openai": ("openai", "openai"),
    "voyage": ("agentforge_voyage", "voyage"),
    "neo4j": ("neo4j", "neo4j"),
    "pgvector": ("asyncpg", "pgvector"),
    "surrealdb": ("surrealdb", "surrealdb"),
}

# Credentialed drivers → the env var holding their API key (the default when the
# config doesn't name one). Bedrock is intentionally absent: the AWS credential
# chain is resolved by boto3 at call time, not from a single env var.
_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "voyage": "VOYAGE_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def install_command(extra: str) -> str:
    return f"pip install '{PACKAGE}[{extra}]'"


def _module_present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def missing_extra(driver: str) -> tuple[str, str] | None:
    """``(probe_module, extra)`` when ``driver`` needs an extra that is **not**
    installed; ``None`` when it is a base driver or its dependency is present."""
    req = _REQUIREMENTS.get(driver)
    if req is None:
        return None
    module, extra = req
    return None if _module_present(module) else req


class ProviderUnavailable(ImportError):
    """A selected driver's optional dependency is not installed. Carries the
    install command so the **in-process** path (a framework agent using
    ``code_graph_tools(...)``) fails with the fix, not a bare
    ``ModuleNotFoundError``. The CLI preflight raises the same guidance up front."""

    def __init__(self, driver: str, extra: str, role: str) -> None:
        self.driver = driver
        self.extra = extra
        self.role = role
        self.install_cmd = install_command(extra)
        super().__init__(
            f"{role} driver {driver!r} needs the {extra!r} extra — run: {self.install_cmd}"
        )


def ensure_installed(driver: str, role: str) -> None:
    """Raise :class:`ProviderUnavailable` if ``driver`` needs an uninstalled
    extra. Live builders call this before importing their SDK so the in-process
    path is guided too."""
    miss = missing_extra(driver)
    if miss is not None:
        raise ProviderUnavailable(driver, miss[1], role)


@dataclass(frozen=True)
class Problem:
    """One thing wrong with a resolved config, with the fix. ``severity`` is
    ``error`` (blocks a write run) or ``warning`` (surfaced, non-blocking)."""

    scope: str  # repo/member label this problem belongs to
    severity: str
    summary: str
    fix: str = ""

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


def _import_problem(scope: str, role: str, driver: str) -> Problem | None:
    miss = missing_extra(driver)
    if miss is None:
        return None
    return Problem(
        scope, "error", f"{role} driver {driver!r} is not installed", install_command(miss[1])
    )


def _cred_problem(scope: str, role: str, driver: str, api_key_env: str) -> Problem | None:
    env = api_key_env or _KEY_ENV.get(driver, "")
    if env and driver in _KEY_ENV and not os.environ.get(env):
        return Problem(
            scope, "error", f"{role} driver {driver!r}: ${env} is not set", f"export {env}=..."
        )
    return None


def check_embedder(scope: str, cfg: EmbedConfig) -> list[Problem]:
    if not cfg.enabled:  # ENH-023: a structure-only repo needs no embedder
        return []
    imp = _import_problem(scope, "embedder", cfg.driver)
    if imp is not None:
        return [imp]  # no point checking creds for an uninstalled driver
    cred = _cred_problem(scope, "embedder", cfg.driver, cfg.api_key_env)
    return [cred] if cred is not None else []


def check_enrich(scope: str, cfg: EnrichConfig) -> list[Problem]:
    if not cfg.enabled:
        return []
    imp = _import_problem(scope, "enricher", cfg.provider)
    if imp is not None:
        return [imp]
    cred = _cred_problem(scope, "enricher", cfg.provider, cfg.api_key_env)
    return [cred] if cred is not None else []


def check_store(scope: str, cfg: StoreConfig) -> list[Problem]:
    problems = []
    for label, driver in (("store graph", cfg.graph.driver), ("store vectors", cfg.vectors.driver)):
        imp = _import_problem(scope, label, driver)
        if imp is not None:
            problems.append(imp)
    return problems


def preflight(
    config: ConfigSource,
    scope: str = "repo",
    *,
    embed: bool = False,
    enrich: bool = False,
    store: bool = True,
) -> list[Problem]:
    """Problems with the resolved ``config`` for the roles a run will exercise.
    Empty list = ready. ``store`` is checked by default (every verb opens it);
    ``embed``/``enrich`` only when that work will run."""
    problems: list[Problem] = []
    if store:
        problems += check_store(scope, StoreConfig.load(config))
    if embed:
        problems += check_embedder(scope, EmbedConfig.load(config))
    if enrich:
        problems += check_enrich(scope, EnrichConfig.load(config))
    return problems
