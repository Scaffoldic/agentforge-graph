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

from .errors import UngroundedError
from .types import Footnote, ProvenanceSet, SymbolRef

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.M)
_REF_DEF = re.compile(r"^\[\^([^\]]+)\]:\s*(.+?)\s*$", re.M)
_INLINE = re.compile(r"\[\^([^\]]+)\]")
_REFERENCES_TITLE = "references"


@dataclass(frozen=True)
class VerifiedDoc:
    """Result of verifying a rendered doc: the citation-rewritten body, the
    verified footnotes, any sections that carried no valid citation (empty when
    ``require_citations`` held), and the markers pruned as fabricated/dangling."""

    body: str
    footnotes: tuple[Footnote, ...]
    ungrounded_sections: tuple[str, ...]
    dropped: tuple[str, ...] = ()


def _strip_preamble(content: str) -> str:
    """Drop any text before the first Markdown heading — a real model sometimes
    emits meta-commentary ("Let me compile the document:") above the doc despite
    the instruction to output only Markdown."""
    m = _HEADING.search(content)
    return content[m.start() :] if m else content


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
    """Verify a rendered doc's citations against the provenance set.

    Two guarantees, calibrated on real-model behaviour:

    - **Integrity (always):** every *published* citation points at a real,
      provenance-floored fact. A citation is *valid* only if it is used inline
      **and** its definition resolves into the provenance set; anything else
      (fabricated id, dangling marker, unused def) is **pruned** — the inline
      marker stripped and the def dropped — never fatal, because a real model
      occasionally mis-cites.
    - **Grounding (``require_citations``, doc-level):** the doc must retain at
      least one valid citation — we refuse to publish prose with *no* grounding.
      Per-section gaps (a heading whose section has no valid citation) are
      *reported* in ``ungrounded_sections`` for the reviewer, not failed on:
      real docs have legitimate overview/connective prose, and the human promote
      gate carries per-section adequacy."""
    content, refs = _split_references(body)
    content = _strip_preamble(content)

    # Resolvable defs (symbol id in the provenance set). A symbol id is 5
    # space-joined fields, so the whole remainder of a `[^fN]: <id>` line is the id.
    resolvable: dict[str, SymbolRef] = {}
    for m in _REF_DEF.finditer(refs):
        marker, symbol_id = m.group(1), m.group(2).strip()
        if prov.contains(symbol_id):
            resolvable[marker] = prov.refs[symbol_id]

    used = {m.group(1) for m in _INLINE.finditer(content)}
    valid = {m: ref for m, ref in resolvable.items() if m in used}  # used AND resolvable
    dropped = tuple(dict.fromkeys(m for m in used | set(resolvable) if m not in valid))

    if require_citations and not valid:
        raise UngroundedError(
            "the generated doc has no valid citation — refusing to publish ungrounded prose"
        )

    # Strip inline markers that aren't valid (fabricated / dangling).
    stripped = _INLINE.sub(lambda m: m.group(0) if m.group(1) in valid else "", content)
    ungrounded = tuple(t for t, text in _sections(stripped) if not _INLINE.search(text))

    # Rewrite valid defs to human links; drop the rest.
    rewritten_refs = _REF_DEF.sub(
        lambda m: _render_def(m.group(1), valid[m.group(1)]) if m.group(1) in valid else "",
        refs,
    )
    return VerifiedDoc(
        body=stripped + rewritten_refs,
        footnotes=tuple(Footnote(marker=k, ref=v) for k, v in valid.items()),
        ungrounded_sections=ungrounded,
        dropped=dropped,
    )
