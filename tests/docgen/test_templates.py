"""feat-016 chunk 4: templates registered for every doc type + task rendering."""

from __future__ import annotations

import pytest

from agentforge_graph.core import NodeKind
from agentforge_graph.docgen.errors import DocDisabled
from agentforge_graph.docgen.templates.base import TEMPLATES, get_template
from agentforge_graph.docgen.types import (
    DocTarget,
    DocType,
    GroundedFact,
    GroundedPack,
    SymbolRef,
)


def test_all_four_types_have_templates() -> None:
    assert set(TEMPLATES) == set(DocType)


def test_unregistered_template_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(TEMPLATES, DocType.DESIGN)
    with pytest.raises(DocDisabled, match="design"):
        get_template(DocType.DESIGN)


def test_build_task_embeds_seed_facts_and_sections() -> None:
    ref = SymbolRef(id="ckg py repo app.py Repo#", kind=NodeKind.CLASS, name="Repo", path="app.py")
    pack = GroundedPack(
        target=DocTarget(type=DocType.COMPONENT, scope="app.py"),
        facts=(GroundedFact(text="Repo is the store", ref=ref, source="parsed"),),
        notes=("File summary: x",),
    )
    task = get_template(DocType.COMPONENT).build_task(pack)
    assert "ckg py repo app.py Repo#" in task  # the citable id is offered
    assert "Repo is the store" in task
    assert "Scope: `app.py`" in task
    assert "## References" in task
    assert "## Public API" in task  # a template section
    assert "NOT citable" in task  # notes framing marked non-citable
