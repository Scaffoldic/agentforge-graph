"""Structured errors for grounded doc generation (feat-016).

Every failure a caller can act on is a typed ``DocgenError`` carrying a
human-readable *why* — surfaced by the CLI as a stderr message + exit 2
(the ENH-026 convention), never a stack trace.
"""

from __future__ import annotations


class DocgenError(Exception):
    """Base for every doc-generation error."""


class UngroundedError(DocgenError):
    """A generated section cites no supporting fact while ``require_citations``
    is on — we refuse to publish confident prose we cannot attribute."""


class BadCitationError(DocgenError):
    """A footnote cites a symbol that never appeared in the run's provenance set
    (seed ∪ captured tool results) — a fabricated citation."""


class DocDisabled(DocgenError):
    """Doc generation is disabled, or the requested doc type is not in
    ``docgen.types``."""


class PromoteRequired(DocgenError):
    """An operation (``sync``) needs an *accepted* doc, but the doc is still a
    draft — promote it first (the human review gate)."""
