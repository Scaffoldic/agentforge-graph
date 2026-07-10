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

from .citations import VerifiedDoc, verify_citations
from .errors import (
    BadCitationError,
    DocDisabled,
    DocgenError,
    PromoteRequired,
    UngroundedError,
)
from .generator import DocGenerator
from .manifest import Manifest, content_sha
from .recipes import RECIPES, Recipe, get_recipe, register
from .runner import AgentDocRunner
from .staleness import DOCS_CONSUMER, is_stale, stale_docs
from .templates.base import SYSTEM_PROMPT, Template, get_template
from .toolset import capture_refs, grounded_tools
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
    # recipes
    "Recipe",
    "RECIPES",
    "get_recipe",
    "register",
    # citations
    "verify_citations",
    "VerifiedDoc",
    # templates
    "Template",
    "get_template",
    "SYSTEM_PROMPT",
    # generation (Agent loop)
    "DocGenerator",
    "AgentDocRunner",
    "grounded_tools",
    "capture_refs",
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
