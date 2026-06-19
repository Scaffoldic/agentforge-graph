"""FrameworkPack ABC defaults + registry — the surface community packs rely on."""

from __future__ import annotations

from agentforge_graph.frameworks import (
    BUILTIN_FRAMEWORK_PACKS,
    FrameworkRegistry,
    builtin_framework_registry,
)
from agentforge_graph.frameworks.packs.fastapi import FASTAPI_PACK
from agentforge_graph.frameworks.packs.sqlalchemy import SQLALCHEMY_PACK


async def test_default_resolve_and_coupled_files_are_inert() -> None:
    # routes-only packs have no pass-2: resolve() yields no edges, no file coupled.
    assert await FASTAPI_PACK.resolve(store=None) == []  # type: ignore[arg-type]
    assert FASTAPI_PACK.coupled_files("urls.py") is False


def test_registry_lookup() -> None:
    reg = builtin_framework_registry()
    assert FASTAPI_PACK in BUILTIN_FRAMEWORK_PACKS
    assert reg.by_name("fastapi") is FASTAPI_PACK
    assert reg.by_name("django") is None
    assert reg.by_name("sqlalchemy") is SQLALCHEMY_PACK
    assert set(reg.for_language("python")) == {FASTAPI_PACK, SQLALCHEMY_PACK}
    assert reg.for_language("rust") == []


def test_registry_packs_is_a_copy() -> None:
    reg = FrameworkRegistry([FASTAPI_PACK])
    reg.packs.append(FASTAPI_PACK)  # mutating the returned list must not leak
    assert reg.packs == [FASTAPI_PACK]
