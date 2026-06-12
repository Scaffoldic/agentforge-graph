"""Node and edge kind vocabularies for the code knowledge graph.

The full vocabulary is locked at 0.1 — including the higher-level kinds
whose producers ship later (feat-010/011/012) — so stores and queries
handle every kind from day one and no schema migration is needed when a
later producer lands. See ADR-0005.
"""

from __future__ import annotations

from enum import StrEnum


class NodeKind(StrEnum):
    """Every node kind the graph may contain. Locked at 0.1 (ADR-0005)."""

    # --- structural (produced by feat-002) ---
    REPOSITORY = "Repository"
    PACKAGE = "Package"
    FILE = "File"
    CLASS = "Class"
    INTERFACE = "Interface"
    FUNCTION = "Function"
    METHOD = "Method"
    VARIABLE = "Variable"
    TYPE_ALIAS = "TypeAlias"

    # --- retrieval (feat-005 / feat-010) ---
    CHUNK = "Chunk"
    DOC_CHUNK = "DocChunk"

    # --- higher-level: reserved now, produced later (ADR-0005) ---
    DECISION = "Decision"  # feat-010
    ROUTE = "Route"  # feat-011
    DATA_MODEL = "DataModel"  # feat-011
    SERVICE = "Service"  # feat-011
    SUMMARY = "Summary"  # feat-012
    PATTERN_TAG = "PatternTag"  # feat-012


class EdgeKind(StrEnum):
    """Every edge kind the graph may contain. Locked at 0.1 (ADR-0005)."""

    # --- structural (feat-002) ---
    CONTAINS = "CONTAINS"
    IMPORTS = "IMPORTS"
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPLEMENTS = "IMPLEMENTS"
    REFERENCES = "REFERENCES"

    # --- retrieval / docs (feat-005 / feat-010) ---
    CHUNK_OF = "CHUNK_OF"
    DESCRIBES = "DESCRIBES"

    # --- decisions (feat-010) ---
    GOVERNS = "GOVERNS"
    SUPERSEDES = "SUPERSEDES"

    # --- framework (feat-011) ---
    HANDLED_BY = "HANDLED_BY"
    INJECTED_INTO = "INJECTED_INTO"
    HAS_FIELD = "HAS_FIELD"
    RELATES_TO = "RELATES_TO"

    # --- enrichment (feat-012) ---
    SUMMARIZES = "SUMMARIZES"
    TAGGED = "TAGGED"
