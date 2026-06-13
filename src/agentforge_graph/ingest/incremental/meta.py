"""``IndexMeta`` — the persisted ``.ckg/meta.json`` manifest (feat-004).

Extends the minimal ``{schema_version, indexed_commit}`` that ``Store.open``
writes on first open into the full state the next diff needs: the git commit
the index was built at, a per-language pack fingerprint, and a per-file
content-hash manifest. Saved atomically (temp + ``os.replace``) and **last**
in a refresh, so a crash leaves the previous, consistent manifest in place and
the refresh simply re-runs from the old commit.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

from agentforge_graph.ingest.pack import LanguagePack
from agentforge_graph.store.facade import STORE_SCHEMA_VERSION

_META = "meta.json"


def pack_fingerprint(pack: LanguagePack) -> str:
    """A content fingerprint of everything about a pack that changes its
    output: the two query files, the module style, and the descriptor map.
    Bumping a ``.scm`` therefore changes the fingerprint and forces a full
    re-index (correctness over speed) — no manual version bookkeeping."""
    rules = ",".join(f"{k}={v.value}" for k, v in sorted(pack.descriptor_rules.kinds.items()))
    blob = " ".join([pack.structure_queries, pack.reference_queries, pack.module_style, rules])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class IndexMeta(BaseModel):
    """The on-disk index manifest. Unknown keys are ignored on load, so an
    older ``meta.json`` (just ``schema_version`` + ``indexed_commit``) upgrades
    cleanly — the missing fields default and repopulate on the next index."""

    schema_version: int = STORE_SCHEMA_VERSION
    indexed_commit: str = ""  # git HEAD at last index ("" if non-git)
    pack_versions: dict[str, str] = Field(default_factory=dict)  # lang_slug -> fingerprint
    files: dict[str, str] = Field(default_factory=dict)  # repo-rel path -> content_hash

    @classmethod
    def load(cls, root: str | Path) -> IndexMeta:
        p = Path(root) / _META
        if not p.exists():
            return cls()
        return cls.model_validate(json.loads(p.read_text()))

    def save(self, root: str | Path) -> None:
        p = Path(root) / _META
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(_META + ".tmp")
        tmp.write_text(json.dumps(self.model_dump(), indent=2, sort_keys=True))
        os.replace(tmp, p)  # atomic on POSIX; the manifest is never half-written

    def is_indexed(self) -> bool:
        """True once a real index exists (files recorded or a commit pinned)."""
        return bool(self.files) or bool(self.indexed_commit)

    def packs_changed(self, packs: list[LanguagePack]) -> bool:
        """A pack fingerprint changed (or a new pack appeared) since last index
        → extraction semantics differ, force a full rebuild."""
        current = {p.lang_slug: pack_fingerprint(p) for p in packs}
        return any(self.pack_versions.get(slug) != fp for slug, fp in current.items())

    @staticmethod
    def fingerprints(packs: list[LanguagePack]) -> dict[str, str]:
        return {p.lang_slug: pack_fingerprint(p) for p in packs}
