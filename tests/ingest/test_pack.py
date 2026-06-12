"""LanguagePack + PackRegistry: module-path mapping and lookups."""

from __future__ import annotations

from agentforge_graph.ingest import PackRegistry
from agentforge_graph.ingest.packs import BUILTIN_PACKS, builtin_registry
from agentforge_graph.ingest.packs.python import PYTHON_PACK


def test_python_module_path() -> None:
    assert PYTHON_PACK.module_path("a/b/c.py") == "a.b.c"
    assert PYTHON_PACK.module_path("pkg/__init__.py") == "pkg"
    assert PYTHON_PACK.module_path("m.py") == "m"


def test_registry_lookup() -> None:
    reg = PackRegistry([PYTHON_PACK])
    assert reg.for_extension(".py") is PYTHON_PACK
    assert reg.for_extension(".rs") is None
    assert reg.for_language("python") is PYTHON_PACK
    assert reg.for_language("rust") is None
    assert reg.packs == [PYTHON_PACK]


def test_builtin_registry() -> None:
    assert PYTHON_PACK in BUILTIN_PACKS
    assert builtin_registry().for_extension(".py") is PYTHON_PACK


def test_pack_loaded_scm_nonempty() -> None:
    assert "class_definition" in PYTHON_PACK.structure_queries
    assert "call" in PYTHON_PACK.reference_queries
