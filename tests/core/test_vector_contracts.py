"""Validation of the vector-store value models added in feat-003."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentforge_graph.core import Embedded, NodeKind, ScoredRef


def test_embedded_round_trips() -> None:
    e = Embedded(ref="ckg py r f.py x.", vector=[0.1, 0.2], kind=NodeKind.CHUNK, attrs={"o": 1})
    assert e.vector == [0.1, 0.2]
    assert e.kind is NodeKind.CHUNK


def test_embedded_rejects_empty_vector() -> None:
    with pytest.raises(ValidationError):
        Embedded(ref="r", vector=[], kind=NodeKind.CHUNK)


def test_scored_ref_defaults() -> None:
    s = ScoredRef(ref="r", score=0.9)
    assert s.attrs == {}
