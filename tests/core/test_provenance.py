from __future__ import annotations

import pytest

from agentforge_graph.core import Provenance, Source


def test_helper_constructors_set_source() -> None:
    assert Provenance.parsed("x").source is Source.PARSED
    assert Provenance.resolved("x").source is Source.RESOLVED
    assert Provenance.manual("x").source is Source.MANUAL
    assert Provenance.llm("x", 0.8).source is Source.LLM


def test_parsed_is_full_confidence() -> None:
    assert Provenance.parsed("x").confidence == 1.0


def test_non_llm_confidence_below_one_rejected() -> None:
    with pytest.raises(ValueError, match="only valid for source=llm"):
        Provenance(source=Source.PARSED, extractor="x", confidence=0.5)


def test_confidence_out_of_range_rejected() -> None:
    with pytest.raises(ValueError, match=r"\[0.0, 1.0\]"):
        Provenance.llm("x", 1.5)


def test_llm_accepts_partial_confidence() -> None:
    assert Provenance.llm("enricher", 0.7).confidence == 0.7


def test_provenance_is_frozen() -> None:
    p = Provenance.parsed("x")
    with pytest.raises(ValueError):
        p.confidence = 0.5  # type: ignore[misc]
