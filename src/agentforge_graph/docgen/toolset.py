"""The grounded toolset + provenance capture (feat-016).

The Agent expands the seed pack by calling the read-only feat-008 ckg tools —
the *same* ``Tool`` instances an MCP client gets, standalone-usable
(``code_graph_tools`` docstring: "Pass straight to ``Agent(tools=…)``"). Those
tools return JSON whose fact items carry ``id`` + ``provenance``, so we capture
the run's provenance set by scanning the observations — **tool-agnostic, no
second store handle**.

Two guarantees live here:

- **The tool boundary is the only fact source.** A symbol is citable only if it
  appears in a captured tool result (or the seed) — the model cannot invent one.
- **The anti-echo-chamber floor.** A captured item whose ``provenance`` is
  ``llm`` is dropped, so a generated/summarised (llm-sourced) fact can inform the
  model's search but is never a citable ground-truth fact.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from agentforge_graph.core import NodeKind, Source, SymbolID

from .types import SymbolRef

if TYPE_CHECKING:
    from agentforge_graph.config import ConfigSource


def grounded_tools(repo_path: str, config: ConfigSource = None) -> list[Any]:
    """The read-only ckg ``Tool`` instances the doc Agent may call. These are the
    feat-008 tools verbatim (all read-only); no write tool is ever included."""
    from agentforge_graph.serve import code_graph_tools

    return code_graph_tools(repo_path, config)


def _valid_symbol_id(value: str) -> bool:
    try:
        SymbolID.parse(value)
    except ValueError:
        return False
    return True


def _ref_from_obj(symbol_id: str, obj: dict[str, Any]) -> SymbolRef | None:
    kind_raw = obj.get("kind")
    if not isinstance(kind_raw, str):
        return None
    try:
        kind = NodeKind(kind_raw)
    except ValueError:
        return None
    span = obj.get("span")
    span_t = (span[0], span[1]) if isinstance(span, (list, tuple)) and len(span) == 2 else None
    path = obj.get("path") or SymbolID.parse(symbol_id).path
    return SymbolRef(id=symbol_id, kind=kind, name=str(obj.get("name", "")), path=path, span=span_t)


def _collect(node: Any, out: dict[str, SymbolRef]) -> None:
    if isinstance(node, list):
        for v in node:
            _collect(v, out)
        return
    if not isinstance(node, dict):
        return
    sid = node.get("id")
    if (
        isinstance(sid, str)
        and sid not in out
        and _valid_symbol_id(sid)
        # Anti-echo-chamber floor: an llm-sourced fact is never citable.
        and node.get("provenance") != Source.LLM.value
    ):
        ref = _ref_from_obj(sid, node)
        if ref is not None:
            out[sid] = ref
    for v in node.values():
        _collect(v, out)


def capture_refs(observations: Iterable[str]) -> dict[str, SymbolRef]:
    """Scan tool observation strings for citable graph facts.

    Each fact-bearing ckg tool returns ``ContextPack.to_dict()``-style JSON whose
    items carry ``id`` / ``kind`` / ``name`` / ``path`` / ``span`` / ``provenance``.
    We walk every observation, keep items with a valid :class:`SymbolID` and a
    ``>= parsed`` provenance, and build a ``{id: SymbolRef}`` map. Non-JSON
    observations (e.g. the rendered repo map, or the model's prose) parse-fail and
    are skipped."""
    out: dict[str, SymbolRef] = {}
    for text in observations:
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        _collect(data, out)
    return out
