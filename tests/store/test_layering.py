"""ADR-0001: the storage adapters (and the ckg.yaml config reader) are
deterministic engine code and must not import the AgentForge framework.

Checked by parsing the source (not at runtime), so a stray import is caught
even on a code path tests don't execute.
"""

from __future__ import annotations

import ast
import pathlib

import agentforge_graph.config as config
import agentforge_graph.store as store


def _is_framework_import(module: str) -> bool:
    # "agentforge" the framework — NOT "agentforge_graph" (us).
    return module == "agentforge" or module.startswith("agentforge.")


def _offenders(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [
                f"{path.name}: import {a.name}" for a in node.names if _is_framework_import(a.name)
            ]
        elif isinstance(node, ast.ImportFrom) and _is_framework_import(node.module or ""):
            found.append(f"{path.name}: from {node.module} import ...")
    return found


def test_store_does_not_import_agentforge() -> None:
    files = sorted(pathlib.Path(store.__file__).parent.glob("*.py"))
    files.append(pathlib.Path(config.__file__))
    offenders = [o for path in files for o in _offenders(path)]
    assert not offenders, offenders
