"""ADR-0001: chunking and embed are deterministic engine packages and must
not import the AgentForge framework (boto3 is fine — it's not the framework).
"""

from __future__ import annotations

import ast
import pathlib

import agentforge_graph.chunking as chunking
import agentforge_graph.embed as embed


def _is_framework_import(module: str) -> bool:
    return module == "agentforge" or module.startswith("agentforge.")


def _offenders(root: pathlib.Path) -> list[str]:
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found += [
                    f"{path.name}: import {a.name}"
                    for a in node.names
                    if _is_framework_import(a.name)
                ]
            elif isinstance(node, ast.ImportFrom) and _is_framework_import(node.module or ""):
                found.append(f"{path.name}: from {node.module} import ...")
    return found


def test_chunking_and_embed_do_not_import_agentforge() -> None:
    offenders = _offenders(pathlib.Path(chunking.__file__).parent)
    offenders += _offenders(pathlib.Path(embed.__file__).parent)
    assert not offenders, offenders
