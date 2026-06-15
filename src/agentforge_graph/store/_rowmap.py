"""Pure ``Node``/``Edge`` ↔ property-row mapping, shared by every property-graph
adapter (Kuzu embedded, Neo4j server — ENH-004). No DB driver imports: the open
schema (arbitrary kinds, free-form ``attrs``) is flattened to a fixed set of
scalar properties (``kind``, ``name``, span, provenance, ``origin_path``) with
``attrs`` as a JSON string, so an unrecognized kind round-trips with no DDL
change (ADR-0005). Each backend supplies the storage; this supplies the shape.
"""

from __future__ import annotations

import json
from typing import Any

from agentforge_graph.core import Edge, EdgeKind, Node, NodeKind, Provenance, Source, SymbolID

# Trust ordering (PARSED is highest-trust): a node passes a ``min_source`` floor
# iff its source rank is >= the floor's.
SOURCE_RANK = {Source.LLM: 0, Source.RESOLVED: 1, Source.MANUAL: 1, Source.PARSED: 2}


def dump_attrs(attrs: dict[str, Any]) -> str:
    return json.dumps(attrs, sort_keys=True)


def load_attrs(s: str | None) -> dict[str, Any]:
    return json.loads(s) if s else {}


def acceptable_sources(floor: Source) -> list[str]:
    threshold = SOURCE_RANK[floor]
    return [s.value for s, rank in SOURCE_RANK.items() if rank >= threshold]


def node_params(node: Node, origin_path: str) -> dict[str, Any]:
    span_start, span_end = node.span if node.span is not None else (None, None)
    p = node.provenance
    return {
        "id": node.id,
        "kind": node.kind.value,
        "name": node.name,
        "span_start": span_start,
        "span_end": span_end,
        "attrs": dump_attrs(node.attrs),
        "sym_path": SymbolID.parse(node.id).path,
        "prov_source": p.source.value,
        "prov_extractor": p.extractor,
        "prov_commit": p.commit,
        "prov_confidence": p.confidence,
        "origin_path": origin_path,
    }


def edge_params(edge: Edge, origin_path: str) -> dict[str, Any]:
    p = edge.provenance
    return {
        "src": edge.src,
        "dst": edge.dst,
        "kind": edge.kind.value,
        "attrs": dump_attrs(edge.attrs),
        "prov_source": p.source.value,
        "prov_extractor": p.extractor,
        "prov_commit": p.commit,
        "prov_confidence": p.confidence,
        # An edge that carries its own owner file (resolver edges, feat-004) wins;
        # otherwise the caller's stamp (the upserted file's path).
        "origin_path": edge.origin_path or origin_path,
        "resolved_from": "",
    }


def prov_from_row(d: dict[str, Any]) -> Provenance:
    # The validating constructor — a corrupt row fails loudly, not silently.
    return Provenance(
        source=Source(d["prov_source"]),
        extractor=d["prov_extractor"],
        commit=d["prov_commit"],
        confidence=d["prov_confidence"],
    )


def node_from_row(d: dict[str, Any]) -> Node:
    # span may be absent (Neo4j drops null properties) or present-but-None (Kuzu).
    span_start = d.get("span_start")
    span = (span_start, d.get("span_end")) if span_start is not None else None
    return Node(
        id=d["id"],
        kind=NodeKind(d["kind"]),
        name=d["name"],
        span=span,
        attrs=load_attrs(d["attrs"]),
        provenance=prov_from_row(d),
    )


def edge_from_row(d: dict[str, Any], src: str, dst: str) -> Edge:
    return Edge(
        src=src,
        dst=dst,
        kind=EdgeKind(d["kind"]),
        attrs=load_attrs(d["attrs"]),
        provenance=prov_from_row(d),
    )
