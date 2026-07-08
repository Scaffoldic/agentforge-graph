"""The queryable schema — node/edge kinds + the curated property catalogue.

This is the vocabulary a caller writes against, and the single source of truth
that (a) the validator uses to accept/reject property references and (b) the
per-backend compilers (chunk 2) use to map a logical property name to its
physical column. The physical columns are the *shared* row schema every
property-graph adapter persists (``store/_rowmap.py``): ``name``, ``kind``,
``sym_path``, ``span_start``/``span_end`` and the ``prov_*`` provenance columns.
Because that mapping is identical across Kuzu/Neo4j/SurrealDB, ``f.path`` &
friends resolve the same way on every backend — portability by construction.

Anything not in the curated set is addressable as ``n.attrs.<key>`` — an opaque
passthrough over the node's free-form ``attrs`` JSON (compared as a string).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentforge_graph.core import EdgeKind, NodeKind

# Bumped when the accepted grammar/semantics change (minor = additive clause,
# major = semantics change). Reported by ``ckg status`` so long-lived clients
# detect a mismatch. Tracks store/query/GRAMMAR.md.
QUERY_LANG_VERSION = "1.0"

# Prefix for opaque free-form attribute access: ``n.attrs.<key>``.
ATTRS_PREFIX = "attrs"


@dataclass(frozen=True)
class PropertySpec:
    """A curated, queryable node property and its physical backing column."""

    name: str  # logical name written in a query (the ``x`` in ``f.x``)
    column: str  # physical column in the shared row schema (_rowmap.py)
    type: str  # "str" | "int" | "float"
    doc: str


# The curated node properties, mapped to the shared physical row schema. Order
# is display order for ``ckg query --schema``.
NODE_PROPERTIES: tuple[PropertySpec, ...] = (
    PropertySpec("name", "name", "str", "the symbol's name"),
    PropertySpec("kind", "kind", "str", "the node kind (also filterable as a :Label)"),
    PropertySpec("path", "sym_path", "str", "repo-relative file path of the symbol"),
    PropertySpec("start_line", "span_start", "int", "1-based start line of the symbol's span"),
    PropertySpec("end_line", "span_end", "int", "1-based end line of the symbol's span"),
    PropertySpec("source", "prov_source", "str", "provenance: parsed | resolved | llm | manual"),
    PropertySpec("extractor", "prov_extractor", "str", "producer name + version"),
    PropertySpec("commit", "prov_commit", "str", "git sha the fact was derived at"),
    PropertySpec("confidence", "prov_confidence", "float", "provenance confidence in [0.0, 1.0]"),
)

PROPERTY_BY_NAME: dict[str, PropertySpec] = {p.name: p for p in NODE_PROPERTIES}


def is_known_property(path: tuple[str, ...]) -> bool:
    """True if a property path is addressable: a curated single-segment name,
    or an ``attrs.<key...>`` opaque path (at least one key after ``attrs``)."""
    if len(path) == 1:
        return path[0] in PROPERTY_BY_NAME
    return path[0] == ATTRS_PREFIX and len(path) >= 2


def is_attrs_ref(path: tuple[str, ...]) -> bool:
    """True for an opaque ``attrs.<key...>`` reference."""
    return len(path) >= 2 and path[0] == ATTRS_PREFIX


@dataclass(frozen=True)
class SchemaDescription:
    """The full queryable vocabulary, for ``ckg query --schema`` / introspection."""

    node_kinds: tuple[str, ...]
    edge_kinds: tuple[str, ...]
    node_properties: tuple[PropertySpec, ...]
    attrs_note: str
    lang_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_lang_version": self.lang_version,
            "node_kinds": list(self.node_kinds),
            "edge_kinds": list(self.edge_kinds),
            "node_properties": [
                {"name": p.name, "type": p.type, "doc": p.doc} for p in self.node_properties
            ],
            "attrs": self.attrs_note,
        }


def describe_schema() -> SchemaDescription:
    """The documented vocabulary callers query against."""
    return SchemaDescription(
        node_kinds=tuple(k.value for k in NodeKind),
        edge_kinds=tuple(k.value for k in EdgeKind),
        node_properties=NODE_PROPERTIES,
        attrs_note=(
            "any other attribute is addressable as n.attrs.<key> (opaque, compared as a string)"
        ),
        lang_version=QUERY_LANG_VERSION,
    )
