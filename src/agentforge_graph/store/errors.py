"""Storage-layer errors. All raised at ``Store.open`` / adapter open time
(fail-at-startup), never mid-index — a half-written graph is worse than a
refused one."""

from __future__ import annotations


class StoreError(Exception):
    """Base for all storage-adapter errors."""


class StoreConfigError(StoreError):
    """Malformed or unreadable ``ckg.yaml`` ``store:`` block."""


class DriverNotFound(StoreConfigError):
    """Config names a graph/vector driver that isn't registered."""


class SchemaVersionError(StoreError):
    """On-disk index schema version differs from this build's. 0.x policy
    is to rebuild the index (the data is derivable)."""
