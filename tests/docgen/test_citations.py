"""feat-016 chunk 2: the citation verifier — the grounding trust boundary."""

from __future__ import annotations

import pytest

from agentforge_graph.core import NodeKind
from agentforge_graph.docgen import (
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

[^f1]: s1
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


def test_fabricated_citation_is_pruned_not_fatal() -> None:
    # [^f1] cites a symbol not in the provenance set → pruned. f2 stays valid, so
    # the doc is grounded overall (doc-level) and does NOT fail; the Overview
    # section is reported as a gap for the reviewer.
    body = _GOOD.replace("[^f1]: s1", "[^f1]: s99")
    v = verify_citations(body, _prov(), require_citations=True)
    assert {f.marker for f in v.footnotes} == {"f2"}
    assert "f1" in v.dropped
    assert "[^f1]" not in v.body  # fabricated marker stripped from the prose
    assert "Overview" in v.ungrounded_sections


def test_dangling_inline_marker_is_stripped() -> None:
    body = _GOOD.replace("[^f2]", "[^f9]", 1)  # inline [^f2] -> [^f9]; f9 has no def
    v = verify_citations(body, _prov(), require_citations=True)
    assert "[^f9]" not in v.body  # dangling marker stripped
    assert "f9" in v.dropped
    assert {f.marker for f in v.footnotes} == {"f1"}  # f2 def now unused -> dropped too
    assert "Behaviour" in v.ungrounded_sections


def test_preamble_before_first_heading_is_stripped() -> None:
    body = "Perfect. Let me compile the document:\n\n" + _GOOD
    v = verify_citations(body, _prov(), require_citations=True)
    assert "Let me compile" not in v.body
    assert v.body.lstrip().startswith("## Overview")


def test_no_valid_citation_fails_when_required() -> None:
    # every citation fabricated → zero grounding → refuse to publish
    body = _GOOD.replace("[^f1]: s1", "[^f1]: s98").replace("[^f2]: s2", "[^f2]: s99")
    with pytest.raises(UngroundedError, match="no valid citation"):
        verify_citations(body, _prov(), require_citations=True)


_UNGROUNDED = """\
## Grounded

Backed by a fact [^f1].

## Speculative

No citation here at all.

## References

[^f1]: s1
"""


def test_partial_grounding_passes_and_reports_gaps() -> None:
    # one grounded section + one uncited section → doc is grounded overall, so it
    # passes even under require_citations; the gap is reported for the reviewer.
    v = verify_citations(_UNGROUNDED, _prov(), require_citations=True)
    assert v.ungrounded_sections == ("Speculative",)
    assert {f.marker for f in v.footnotes} == {"f1"}


def test_ungrounded_section_reported_when_not_required() -> None:
    v = verify_citations(_UNGROUNDED, _prov(), require_citations=False)
    assert v.ungrounded_sections == ("Speculative",)
    assert {f.marker for f in v.footnotes} == {"f1"}


def test_references_block_markers_do_not_count_as_content_citations() -> None:
    # A doc whose only [^..] usage is inside the References block has NO inline
    # citation → zero grounding → refused (the split must exclude the refs block).
    body = "## Lonely\n\nProse with no marker.\n\n## References\n\n[^f1]: s1\n"
    with pytest.raises(UngroundedError, match="no valid citation"):
        verify_citations(body, _prov(), require_citations=True)
