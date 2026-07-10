"""Doc templates — section skeleton + the grounding/citation contract (feat-016).

A template is *data*: a title, an ordered set of section headers the model must
fill, and optional per-type guidance. :meth:`Template.build_task` turns a seed
:class:`GroundedPack` into the concrete task prompt; :data:`SYSTEM_PROMPT` carries
the doc-type-independent grounding discipline. Templates are Python objects (not
``.md.tmpl`` files) — same "data, not core" property, no packaging of template
artifacts.

Adding a doc type = a new :class:`Template` + one :func:`register_template` call.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import DocDisabled
from ..types import DocType, GroundedPack

#: The grounding discipline every doc-generation run is bound by. The citation
#: rules here are what :mod:`docgen.citations` verifies after the run.
SYSTEM_PROMPT = """\
You are a precise technical-documentation writer for a software repository.
You write ONLY from facts grounded in the code knowledge graph — never from
assumption or prior knowledge of similar projects.

Workflow:
- Use the provided ckg_* tools (ckg_search, ckg_symbol, ckg_neighbors,
  ckg_impact, ckg_repo_map, ckg_routes, ckg_decisions) to gather the facts you
  need before writing. The seed facts you are given are a starting point, not the
  whole picture — expand with the tools.
- Be economical. The seed facts are usually enough to write most sections; make
  only a FEW targeted tool calls to fill specific gaps, then write. Do not explore
  exhaustively — a focused, well-cited doc beats a sprawling one.

Grounding rules (STRICT):
- Every substantive claim MUST cite a real fact with a footnote marker like
  [^f1] placed at the end of the sentence.
- Define every marker in a final "## References" section, one per line, as:
      [^f1]: <symbol_id>
  where <symbol_id> is an EXACT id that appeared in a tool result or a seed fact.
- NEVER invent a symbol id, and NEVER cite an id no tool returned.
- If you cannot ground a section from the available facts, write its heading
  followed by a line containing exactly `<!-- UNGROUNDED -->` instead of guessing.

Output ONLY the final Markdown document (headings, prose, and the References
block). Do not include commentary about your process.
"""


@dataclass(frozen=True)
class Template:
    doc_type: DocType
    title: str
    sections: tuple[str, ...]
    guidance: str = ""

    def build_task(self, pack: GroundedPack) -> str:
        lines: list[str] = [f"Write the **{self.title}** for this repository."]
        if pack.target.scope:
            lines.append(f"Scope: `{pack.target.scope}`.")
        if self.guidance:
            lines.append(self.guidance)

        if pack.facts:
            lines.append("\nSeed facts (cite by the id in brackets; verify/expand with tools):")
            for f in pack.facts:
                lines.append(f"- {f.text}  [id: {f.ref.id}]")
        if pack.notes:
            lines.append("\nContext (framing only — NOT citable):")
            lines.extend(f"- {n}" for n in pack.notes)

        lines.append("\nProduce these sections, each grounded with footnote citations:")
        lines.extend(f"## {s}" for s in self.sections)
        lines.append("\nEnd with a `## References` block defining every [^fN] marker you used.")
        return "\n".join(lines)


TEMPLATES: dict[DocType, Template] = {}


def register_template(template: Template) -> Template:
    TEMPLATES[template.doc_type] = template
    return template


def get_template(doc_type: DocType) -> Template:
    template = TEMPLATES.get(doc_type)
    if template is None:
        raise DocDisabled(f"no template registered for doc type {doc_type.value!r}")
    return template
