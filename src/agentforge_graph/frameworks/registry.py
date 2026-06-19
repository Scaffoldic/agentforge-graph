"""Framework-pack registry (feat-011). Mirrors the language ``PackRegistry``:
a flat list of built-in packs, resolvable by name or by the language they ride.
Third-party packs register out-of-tree via an entry point later."""

from __future__ import annotations

from .base import FrameworkPack
from .packs.django import DJANGO_PACK
from .packs.express import EXPRESS_PACK
from .packs.fastapi import FASTAPI_PACK
from .packs.flask import FLASK_PACK
from .packs.sqlalchemy import SQLALCHEMY_PACK

BUILTIN_FRAMEWORK_PACKS: list[FrameworkPack] = [
    FASTAPI_PACK,
    SQLALCHEMY_PACK,
    DJANGO_PACK,
    FLASK_PACK,
    EXPRESS_PACK,
]


class FrameworkRegistry:
    def __init__(self, packs: list[FrameworkPack]) -> None:
        self._packs = list(packs)
        self._by_name = {p.name: p for p in packs}

    @property
    def packs(self) -> list[FrameworkPack]:
        return list(self._packs)

    def by_name(self, name: str) -> FrameworkPack | None:
        return self._by_name.get(name)

    def for_language(self, language: str) -> list[FrameworkPack]:
        return [p for p in self._packs if p.language == language]


def builtin_framework_registry() -> FrameworkRegistry:
    return FrameworkRegistry(BUILTIN_FRAMEWORK_PACKS)
