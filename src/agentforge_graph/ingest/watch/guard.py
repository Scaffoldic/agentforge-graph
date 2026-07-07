"""feat-014: the local/central guardrail.

``ckg watch`` writes the working-copy graph and therefore may only run against a
**local, writable, embedded** store. A central store (`store.central_root`) is
CI's job (`ckg ci init`); a read-only store is consume-only (ENH-018). Enforcing
that split here — not in docs — is load-bearing: it is what keeps developers'
machines from racing writes into the shared, authoritative graph.
"""

from __future__ import annotations

from agentforge_graph.config import StoreConfig


class WatchGuardError(Exception):
    """Raised when ``ckg watch`` is pointed at a store it must not write."""


def ensure_watchable(store_cfg: StoreConfig, read_only: bool) -> None:
    """Refuse (raise) unless the store is a local, writable, embedded index."""
    if store_cfg.central_root:
        raise WatchGuardError(
            "refusing to watch a central store (store.central_root is set). "
            "A shared/central index must be built by CI, not a developer's watch "
            "loop — scaffold that with `ckg ci init`. Watch only a local .ckg/ index."
        )
    if read_only or store_cfg.read_only:
        raise WatchGuardError(
            "refusing to watch a read-only store "
            "(store.read_only / --read-only / $CKG_READ_ONLY). "
            "This index is consume-only; watch a writable embedded index instead."
        )
