"""Framework detection (feat-011): which packs are active for a repo.

Honours ``frameworks.enabled`` (``auto`` → detect, ``off`` → none, or an
explicit list) plus ``frameworks.packs`` force-enable. Auto-detection reads
dependency manifests (``pyproject.toml`` / ``requirements*.txt``) and, as a
fallback, samples source text for each pack's import markers — so a repo that
vendors a framework without a manifest still activates.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from agentforge_graph.config import FrameworksConfig

from .base import FrameworkPack
from .registry import FrameworkRegistry

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+")
_SAMPLE_CAP = 256 * 1024  # bytes of source to scan for import markers


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def _dep_name(requirement: str) -> str:
    """The distribution name from a PEP 508 requirement string
    (``fastapi>=0.110`` → ``fastapi``)."""
    m = _NAME_RE.match(requirement.strip())
    return _norm(m.group(0)) if m else ""


def _pyproject_deps(path: Path) -> set[str]:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, tomllib.TOMLDecodeError):
        return set()
    deps: set[str] = set()
    project = data.get("project", {})
    for req in project.get("dependencies", []):
        deps.add(_dep_name(str(req)))
    for group in project.get("optional-dependencies", {}).values():
        deps.update(_dep_name(str(req)) for req in group)
    # poetry-style
    poetry = data.get("tool", {}).get("poetry", {})
    deps.update(_norm(k) for k in poetry.get("dependencies", {}))
    return {d for d in deps if d and d != "python"}


def _requirements_deps(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    deps: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-")):
            deps.add(_dep_name(line))
    return {d for d in deps if d}


def _manifest_deps(repo_path: Path) -> set[str]:
    """Best-effort dependency-name set from common manifests (names only),
    lowercased with ``_``→``-`` so ``Flask_SQLAlchemy`` == ``flask-sqlalchemy``."""
    deps: set[str] = set()
    pyproject = repo_path / "pyproject.toml"
    if pyproject.is_file():
        deps |= _pyproject_deps(pyproject)
    for req in repo_path.glob("requirements*.txt"):
        deps |= _requirements_deps(req)
    return deps


def _source_sample(repo_path: Path, exts: set[str]) -> str:
    """Concatenate up to ``_SAMPLE_CAP`` bytes of source (files matching the
    active languages' extensions) for import-marker confirmation."""
    chunks: list[str] = []
    total = 0
    for path in sorted(repo_path.rglob("*")):
        if total >= _SAMPLE_CAP:
            break
        if not path.is_file() or path.suffix not in exts or ".ckg" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        chunks.append(text)
        total += len(text)
    return "\n".join(chunks)


def active_frameworks(
    repo_path: str | Path,
    config: str | Path | None,
    registry: FrameworkRegistry,
    language_extensions: set[str],
) -> list[FrameworkPack]:
    cfg = FrameworksConfig.load(config)
    enabled = cfg.enabled
    if enabled == "off":
        return []

    root = Path(repo_path)
    forced = set(cfg.packs)

    # Explicit list short-circuits detection (still honour force-enable).
    if isinstance(enabled, list):
        wanted = set(enabled) | forced
        return [p for p in registry.packs if p.name in wanted]

    # "auto": dependency manifest + import-marker fallback.
    deps = _manifest_deps(root)
    needs_sample = any(p.import_markers for p in registry.packs)
    sample = _source_sample(root, language_extensions) if needs_sample else ""
    active: list[FrameworkPack] = []
    for pack in registry.packs:
        if pack.name in forced or pack.detect(deps, sample):
            active.append(pack)
    return active
