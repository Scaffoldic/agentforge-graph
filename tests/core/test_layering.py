"""ADR-0001: the engine core must not import the AgentForge framework.

Checked by parsing the source (not at runtime), so a stray import is
caught even on a code path tests don't execute.
"""

from __future__ import annotations

import ast
import pathlib

import agentforge_graph.core as core


def _is_framework_import(module: str) -> bool:
    # "agentforge" the framework — NOT "agentforge_graph" (us).
    return module == "agentforge" or module.startswith("agentforge.")


def test_core_does_not_import_agentforge() -> None:
    root = pathlib.Path(core.__file__).parent
    offenders: list[str] = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                offenders += [
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if _is_framework_import(a.name)
                ]
            elif isinstance(node, ast.ImportFrom) and _is_framework_import(node.module or ""):
                offenders.append(f"{path.name}: from {node.module} import ...")
    assert not offenders, offenders
