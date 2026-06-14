"""LanguagePack + PackRegistry: module-path mapping and lookups."""

from __future__ import annotations

from agentforge_graph.ingest import PackRegistry
from agentforge_graph.ingest.packs import BUILTIN_PACKS, builtin_registry
from agentforge_graph.ingest.packs.python import PYTHON_PACK


def test_python_module_path() -> None:
    assert PYTHON_PACK.module_path("a/b/c.py") == "a.b.c"
    assert PYTHON_PACK.module_path("pkg/__init__.py") == "pkg"
    assert PYTHON_PACK.module_path("m.py") == "m"


def test_python_resolve_import_absolute_is_identity() -> None:
    # absolute dotted imports are unchanged (importer_module is irrelevant)
    assert PYTHON_PACK.resolve_import("pkg/a.py", "os.path", "pkg.a") == "os.path"
    assert PYTHON_PACK.resolve_import("pkg/a.py", "pkg.util", "pkg.a") == "pkg.util"


def test_python_resolve_import_relative_dots() -> None:
    # BUG-004: leading-dot relative imports resolve against the importer's package.
    # `from .utils import x` in module pkg.core -> pkg.utils
    assert PYTHON_PACK.resolve_import("pkg/core.py", ".utils", "pkg.core") == "pkg.utils"
    # `from . import x` in pkg.core -> the package itself, pkg
    assert PYTHON_PACK.resolve_import("pkg/core.py", ".", "pkg.core") == "pkg"
    # `from ..sib import x` in pkg.sub.mod -> pkg.sib (ascend one level)
    assert PYTHON_PACK.resolve_import("pkg/sub/mod.py", "..sib", "pkg.sub.mod") == "pkg.sib"
    # multi-segment remainder: `from ..a.b import x` in pkg.sub.mod -> pkg.a.b
    assert PYTHON_PACK.resolve_import("pkg/sub/mod.py", "..a.b", "pkg.sub.mod") == "pkg.a.b"
    # an __init__ file *is* its package: `from .util import x` in pkg/__init__.py -> pkg.util
    assert PYTHON_PACK.resolve_import("pkg/__init__.py", ".util", "pkg") == "pkg.util"


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
