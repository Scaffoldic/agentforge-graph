"""Shared fixture: a tiny repo with one class per pattern signal."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from agentforge_graph.ingest import CodeGraph

PATTERNS_CODE = """
class OrderRepository:
    def get(self, id): ...
    def save(self, order): ...
    def delete(self, id): ...
    def list(self): ...


class PaymentService:
    def charge(self, amount): ...


class WidgetFactory:
    def create(self): ...
    def make_widget(self, kind): ...


class ConfigSingleton:
    def get_instance(self): ...


class RequestObserver:
    def notify(self, event): ...
    def subscribe(self, fn): ...


class PlainThing:
    def do_work(self): ...
"""


@pytest.fixture
async def graph(tmp_path: Path) -> AsyncIterator[CodeGraph]:
    repo = tmp_path / "proj"
    repo.mkdir()
    (repo / "app.py").write_text(PATTERNS_CODE)
    cg = await CodeGraph.index(repo_path=repo)
    try:
        yield cg
    finally:
        await cg.close()
