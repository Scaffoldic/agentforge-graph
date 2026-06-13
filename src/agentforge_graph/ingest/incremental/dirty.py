"""``DirtySet`` — the one staleness API every enricher reads (feat-004).

When an incremental refresh changes a file, the symbols it touched (plus their
1-hop neighbours) are *dirtied* for every registered consumer — ``embeddings``
now, ``summaries`` / ``pattern-tags`` / ``routes`` as feat-010/011/012 land.
Each consumer drains its own cursor at its own cadence and marks the ids clean,
so no enricher reinvents "what changed since I last ran". Persisted to
``.ckg/dirty.json`` as ``{consumer: [symbol_id, ...]}`` — a side file, so a
consumer cursor update never rewrites the index manifest (``meta.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

_DIRTY = "dirty.json"


class DirtySet:
    # Known enrichment consumers: embeddings (feat-005), patterns + summaries (feat-012).
    DEFAULT_CONSUMERS = ["embeddings", "patterns", "summaries"]

    def __init__(self, root: str | Path, consumers: list[str] | None = None) -> None:
        self._path = Path(root) / _DIRTY
        self._consumers = list(consumers or self.DEFAULT_CONSUMERS)
        self._state: dict[str, list[str]] = self._load()

    def _load(self) -> dict[str, list[str]]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text())
        return {k: list(v) for k, v in data.items()}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(_DIRTY + ".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, sort_keys=True))
        tmp.replace(self._path)

    async def add(self, ids: list[str]) -> None:
        """Append ``ids`` to every registered consumer's dirty set (deduped,
        order-stable)."""
        if not ids:
            return
        for consumer in self._consumers:
            have = self._state.setdefault(consumer, [])
            seen = set(have)
            for i in ids:
                if i not in seen:
                    seen.add(i)
                    have.append(i)
        self._save()

    async def dirty_for(self, consumer: str) -> list[str]:
        return list(self._state.get(consumer, []))

    async def mark_clean(self, consumer: str, ids: list[str]) -> None:
        drop = set(ids)
        self._state[consumer] = [i for i in self._state.get(consumer, []) if i not in drop]
        self._save()
