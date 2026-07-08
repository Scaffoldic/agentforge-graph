"""agentforge_graph.store.query — the read-only graph query surface (feat-015).

A caller writes a bounded Cypher-subset string; we parse it into our own frozen
``QueryAst`` (the single trust boundary), validate that AST against the locked
feat-001 vocabulary + read-only exclusion rules + the target backend's declared
capabilities, and (chunk 2) compile it per backend and execute it under enforced
bounds. Caller text is never executed directly.

This package is deterministic engine code: it imports only ``core`` and
never ``agentforge`` (ADR-0001). The accepted grammar is specified in
``GRAMMAR.md`` and versioned by ``QUERY_LANG_VERSION``.
"""

from __future__ import annotations

from .ast import QueryAst
from .capability import (
    ALL_CAPABILITIES,
    CORE_TIER,
    QueryCapable,
    QuerySettings,
    ResultTable,
)
from .errors import (
    CapabilityError,
    GuardrailError,
    ParseError,
    QueryDisabled,
    QueryError,
    ValidationError,
)
from .parser import parse_query
from .schema import QUERY_LANG_VERSION, SchemaDescription, describe_schema
from .validator import validate_query

__all__ = [
    # pipeline
    "parse_query",
    "validate_query",
    "describe_schema",
    # types
    "QueryAst",
    "QueryCapable",
    "QuerySettings",
    "ResultTable",
    "SchemaDescription",
    # capabilities
    "CORE_TIER",
    "ALL_CAPABILITIES",
    "QUERY_LANG_VERSION",
    # errors
    "QueryError",
    "ParseError",
    "ValidationError",
    "CapabilityError",
    "GuardrailError",
    "QueryDisabled",
]
