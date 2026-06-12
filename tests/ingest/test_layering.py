"""ADR-0001: the ingestion layer is deterministic engine code and must not
import the AgentForge framework. Checked by parsing the source (recursively,
including the language packs)."""

from __future__ import annotations

import ast
import pathlib

import agentforge_graph.ingest as ingest


def _is_framework_import(module: str) -> bool:
    return module == "agentforge" or module.startswith("agentforge.")


def test_ingest_does_not_import_agentforge() -> None:
    root = pathlib.Path(ingest.__file__).parent
    offenders: list[str] = []
    for path in sorted(root.rglob("*.py")):
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
