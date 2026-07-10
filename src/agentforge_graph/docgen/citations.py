"""Citation verification — the trust boundary for generated prose (feat-016).

The model attributes claims with GFM-style footnote markers (``[^f1]``) and
defines each in a ``## References`` block at the end
(``[^f1]: <symbol-id> …``). This module is the constructive-grounding gate
(feat-015's "validate, don't sanitize", applied to prose):

1. every footnote's symbol must be in the run's :class:`ProvenanceSet` (seed ∪
   captured tool results) — a footnote citing a symbol the tools never returned
   is a fabricated citation (:class:`BadCitationError`);
2. every inline marker must have a definition (no dangling citations);
3. every content section must carry ≥1 citation — an uncited section is
   *ungrounded* (:class:`UngroundedError` when ``require_citations``);
4. the References block is rewritten to human-facing links (symbol → path:span).

It is pure text-in / text-out — no LLM, no I/O — so the guarantee is unit-tested
without a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import BadCitationError, UngroundedError
from .types import Footnote, ProvenanceSet, SymbolRef

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
_REF_DEF = re.compile(r"^\[\^([^\]]+)\]:\s*(.+?)\s*$", re.M)
_INLINE = re.compile(r"\[\^([^\]]+)\]")
_REFERENCES_TITLE = "references"


@dataclass(frozen=True)
class VerifiedDoc:
    """Result of verifying a rendered doc: the citation-rewritten body, the
    verified footnotes, and any sections that carried no citation (empty when
    ``require_citations`` held)."""

    body: str
    footnotes: tuple[Footnote, ...]
    ungrounded_sections: tuple[str, ...]


def _split_references(body: str) -> tuple[str, str]:
    """Return ``(content, references_block)``. The references block is the earliest
    ``References`` heading onward; ``("", body)`` semantics: if there is no such
    heading, the references block is empty."""
    for m in _HEADING.finditer(body):
        if m.group(2).strip().lower() == _REFERENCES_TITLE:
            return body[: m.start()], body[m.start() :]
    return body, ""


def _sections(content: str) -> list[tuple[str, str]]:
    """Split content into ``(title, text)`` sections by ATX heading. Text before
    the first heading (preamble) is not a section."""
    heads = list(_HEADING.finditer(content))
    out: list[tuple[str, str]] = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(content)
        out.append((h.group(2).strip(), content[h.start() : end]))
    return out


def _render_def(marker: str, ref: SymbolRef) -> str:
    loc = ref.path or ""
    if ref.path and ref.span:
        loc = f"{ref.path}:{ref.span[0]}-{ref.span[1]}"
    tail = f" — `{loc}`" if loc else ""
    return f"[^{marker}]: **{ref.name}** ({ref.kind.value}){tail} · `{ref.id}`"


def verify_citations(body: str, prov: ProvenanceSet, *, require_citations: bool) -> VerifiedDoc:
    content, refs = _split_references(body)

    # (1) parse + resolve every footnote definition against the provenance set.
    footnotes: list[Footnote] = []
    defined: dict[str, SymbolRef] = {}
    for m in _REF_DEF.finditer(refs):
        marker = m.group(1)
        symbol_id = m.group(2).split()[0] if m.group(2).split() else ""
        if not prov.contains(symbol_id):
            raise BadCitationError(
                f"footnote [^{marker}] cites {symbol_id!r}, which no tool returned "
                f"(not in the provenance set of {len(prov.refs)} facts)"
            )
        ref = prov.refs[symbol_id]
        defined[marker] = ref
        footnotes.append(Footnote(marker=marker, ref=ref))

    # (2) every inline marker in the content must have a definition.
    used = {m.group(1) for m in _INLINE.finditer(content)}
    dangling = sorted(used - set(defined))
    if dangling:
        raise BadCitationError(
            f"citation marker(s) {dangling} used in the body have no References entry"
        )

    # (3) every content section must carry a valid citation.
    ungrounded = tuple(title for title, text in _sections(content) if not _INLINE.search(text))
    if ungrounded and require_citations:
        raise UngroundedError(
            "ungrounded section(s) with no citable fact: " + ", ".join(repr(s) for s in ungrounded)
        )

    # (4) rewrite the References block to human-facing links.
    rewritten_refs = _REF_DEF.sub(
        lambda m: (
            _render_def(m.group(1), defined[m.group(1)]) if m.group(1) in defined else m.group(0)
        ),
        refs,
    )
    return VerifiedDoc(
        body=content + rewritten_refs,
        footnotes=tuple(footnotes),
        ungrounded_sections=ungrounded,
    )
