"""Locked tool contracts: tool names + input-schema params. Drift fails CI.

feat-015: the tool set is capability-gated — ``ckg_query`` is present only when
the backend is query-capable. The set is asserted for both profiles (enabled /
disabled) so drift on either path fails CI, without depending on the ambient cwd.
"""

from __future__ import annotations

from agentforge_graph.serve.engine import _Engine
from agentforge_graph.serve.server import _tools_for

# (properties, required) per tool — the v1 contract. Every tool also carries the
# optional ENH-020 ``service`` field (federated member selector; inert for a
# single repo), added uniformly below.
_BASE: dict[str, tuple[set[str], set[str]]] = {
    "ckg_repo_map": ({"budget_tokens", "focus"}, set()),
    "ckg_search": ({"query", "k", "mode"}, {"query"}),
    "ckg_symbol": ({"symbol_id", "name", "path"}, set()),
    "ckg_impact": ({"symbol_id", "depth"}, {"symbol_id"}),
    "ckg_neighbors": ({"symbol_id", "edge_kinds", "depth"}, {"symbol_id"}),
    "ckg_status": (set(), set()),
    "ckg_routes": ({"method", "path"}, set()),
    "ckg_decisions": ({"scope", "status"}, set()),
    "ckg_explain": ({"symbol_id"}, {"symbol_id"}),
    "ckg_history": ({"symbol_id"}, {"symbol_id"}),  # feat-009 chunk 3
}
# feat-015: ckg_query is present only in the query-capable profile.
_QUERY = {"ckg_query": ({"query", "limit"}, {"query"})}
_ALL = {**_BASE, **_QUERY}
# ENH-020: the federated member selector is present on every tool, never required.
_EXPECTED = {name: (props | {"service"}, required) for name, (props, required) in _ALL.items()}

_ENABLED = frozenset({"query"})
_DISABLED: frozenset[str] = frozenset()


def _names(capabilities: frozenset[str]) -> set[str]:
    return {t.name for t in _tools_for(_Engine("."), capabilities)}


def test_query_tool_present_only_when_capable() -> None:
    assert _names(_ENABLED) == set(_EXPECTED)
    assert _names(_DISABLED) == set(_BASE)  # ckg_query gated out
    assert "ckg_query" not in _names(_DISABLED)


def test_tool_schemas_match_contract() -> None:
    tools = {t.name: t for t in _tools_for(_Engine("."), _ENABLED)}
    for name, (props, required) in _EXPECTED.items():
        schema = type(tools[name]).input_schema.model_json_schema()
        assert set(schema.get("properties", {})) == props, name
        assert set(schema.get("required", [])) == required, name


def test_every_tool_has_an_llm_description() -> None:
    for t in _tools_for(_Engine("."), _ENABLED):
        assert len(t.description) > 40  # written for tool-choice, not a stub
