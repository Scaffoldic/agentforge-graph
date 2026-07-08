"""Errors for the read-only query surface (feat-015).

One hierarchy, one trust boundary. Everything a caller can do wrong surfaces
as a ``QueryError`` subclass carrying a *why*, never a backend stack trace:

- ``ParseError``      — the text is not in the accepted grammar (syntax).
- ``ValidationError`` — parses, but violates the vocabulary/exclusion rules.
- ``CapabilityError`` — valid, but the target backend does not offer the
  capability tier the query needs (a ``ValidationError`` so callers can catch
  either with one ``except``).
- ``GuardrailError``  — raised at execution time when a bound is hit in a way
  that cannot be turned into a partial result (chunk 2).
- ``QueryDisabled``   — the active backend is not query-capable at all
  (chunk 2, facade).
"""

from __future__ import annotations


class QueryError(Exception):
    """Base for every read-only-query error."""


class ParseError(QueryError):
    """The query text is not in the accepted Cypher-subset grammar."""

    def __init__(
        self, message: str, *, position: int | None = None, query: str | None = None
    ) -> None:
        self.position = position
        self.query = query
        if position is not None and query is not None:
            super().__init__(f"{message} (at offset {position})\n  {query}\n  {' ' * position}^")
        else:
            super().__init__(message)


class ValidationError(QueryError):
    """Parses, but breaks a vocabulary or exclusion rule."""


class CapabilityError(ValidationError):
    """Valid, but the target backend does not support a required capability."""

    def __init__(self, capability: str, supported: frozenset[str]) -> None:
        self.capability = capability
        self.supported = supported
        super().__init__(
            f"this backend does not support '{capability}'; "
            f"supported capabilities: {', '.join(sorted(supported)) or '(none)'}"
        )


class GuardrailError(QueryError):
    """A resource bound was hit and could not be reported as a partial result."""


class QueryDisabled(QueryError):
    """The active storage backend is not query-capable."""

    def __init__(self, driver: str) -> None:
        self.driver = driver
        super().__init__(
            f"the '{driver}' backend does not provide a query surface "
            f"(query.enabled is false for this store)"
        )
