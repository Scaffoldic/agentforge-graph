"""feat-016 chunk 2: the citation verifier — the grounding trust boundary."""

from __future__ import annotations

import pytest

from agentforge_graph.core import NodeKind
from agentforge_graph.docgen import (
    BadCitationError,
    ProvenanceSet,
    SymbolRef,
    UngroundedError,
    verify_citations,
)


def _prov() -> ProvenanceSet:
    return ProvenanceSet(
        refs={
            "s1": SymbolRef(id="s1", kind=NodeKind.CLASS, name="Repo", path="a.py", span=(1, 9)),
            "s2": SymbolRef(id="s2", kind=NodeKind.FUNCTION, name="save", path="a.py", span=(3, 5)),
        }
    )


_GOOD = """\
## Overview

The `Repo` class owns persistence [^f1].

## Behaviour

`save` writes a row [^f2].

## References

[^f1]: s1 the repo
[^f2]: s2
"""


def test_valid_doc_builds_footnotes_and_rewrites() -> None:
    v = verify_citations(_GOOD, _prov(), require_citations=True)
    assert {f.marker for f in v.footnotes} == {"f1", "f2"}
    assert v.ungrounded_sections == ()
    # references rewritten to human-facing links; symbol id retained
    assert "**Repo** (Class)" in v.body
    assert "`a.py:3-5`" in v.body
    assert "`s2`" in v.body
    # inline markers preserved for GFM footnote rendering
    assert "[^f1]" in v.body and "[^f2]" in v.body


def test_bad_citation_symbol_not_in_provenance() -> None:
    body = _GOOD.replace("[^f1]: s1 the repo", "[^f1]: s99")
    with pytest.raises(BadCitationError, match="s99"):
        verify_citations(body, _prov(), require_citations=True)


def test_dangling_inline_marker_without_definition() -> None:
    body = _GOOD.replace("[^f2]", "[^f9]", 1)  # used in body, but only [^f2] defined
    with pytest.raises(BadCitationError, match=r"f9"):
        verify_citations(body, _prov(), require_citations=True)


_UNGROUNDED = """\
## Grounded

Backed by a fact [^f1].

## Speculative

No citation here at all.

## References

[^f1]: s1
"""


def test_ungrounded_section_raises_when_required() -> None:
    with pytest.raises(UngroundedError, match="Speculative"):
        verify_citations(_UNGROUNDED, _prov(), require_citations=True)


def test_ungrounded_section_reported_when_not_required() -> None:
    v = verify_citations(_UNGROUNDED, _prov(), require_citations=False)
    assert v.ungrounded_sections == ("Speculative",)
    assert {f.marker for f in v.footnotes} == {"f1"}


def test_references_block_markers_do_not_count_as_content_citations() -> None:
    # A doc whose only [^..] usage is inside the References block → the single
    # content section is ungrounded (the split must exclude the refs block).
    body = "## Lonely\n\nProse with no marker.\n\n## References\n\n[^f1]: s1\n"
    with pytest.raises(UngroundedError, match="Lonely"):
        verify_citations(body, _prov(), require_citations=True)
