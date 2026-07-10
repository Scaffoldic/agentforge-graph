"""agentforge_graph.docgen — grounded documentation generation (feat-016).

Documentation as a *grounded projection of the graph*: a doc-type recipe seeds a
context pack, an ``agentforge.Agent`` composes the doc while expanding that pack
through a read-only, provenance-floored ckg toolset, and every claim is attributed
to a real graph fact (verified against the captured provenance set). Drafts land
under ``docgen.output_root`` behind a human promote gate and ride the feat-004
``DirtySet`` for freshness.

This is the **framework layer** (it imports ``agentforge`` for the Agent loop),
built over the deterministic engine — it adds no coupling back into ``core`` /
``ingest`` / ``store`` / ``retrieve`` (ADR-0001).
"""

from __future__ import annotations

from .errors import (
    BadCitationError,
    DocDisabled,
    DocgenError,
    PromoteRequired,
    UngroundedError,
)
from .manifest import Manifest, content_sha
from .staleness import DOCS_CONSUMER, is_stale, stale_docs
from .types import (
    DOC_LANG_VERSION,
    STATUS_ACCEPTED,
    STATUS_DRAFT,
    DocArtifact,
    DocTarget,
    DocType,
    Footnote,
    GroundedFact,
    GroundedPack,
    ProvenanceSet,
    SymbolRef,
)

__all__ = [
    # types
    "DocType",
    "DocTarget",
    "SymbolRef",
    "GroundedFact",
    "GroundedPack",
    "ProvenanceSet",
    "Footnote",
    "DocArtifact",
    "DOC_LANG_VERSION",
    "STATUS_DRAFT",
    "STATUS_ACCEPTED",
    # persistence
    "Manifest",
    "content_sha",
    # staleness
    "DOCS_CONSUMER",
    "is_stale",
    "stale_docs",
    # errors
    "DocgenError",
    "UngroundedError",
    "BadCitationError",
    "DocDisabled",
    "PromoteRequired",
]
