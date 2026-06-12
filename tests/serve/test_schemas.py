"""Locked tool contracts: tool names + input-schema params. Drift fails CI."""

from __future__ import annotations

from agentforge_graph.serve import code_graph_tools

# (properties, required) per tool — the v1 contract.
_EXPECTED: dict[str, tuple[set[str], set[str]]] = {
    "ckg_repo_map": ({"budget_tokens", "focus"}, set()),
    "ckg_search": ({"query", "k", "mode"}, {"query"}),
    "ckg_symbol": ({"symbol_id", "name", "path"}, set()),
    "ckg_impact": ({"symbol_id", "depth"}, {"symbol_id"}),
    "ckg_neighbors": ({"symbol_id", "edge_kinds", "depth"}, {"symbol_id"}),
    "ckg_status": (set(), set()),
}


def test_tool_set_is_exactly_v1() -> None:
    assert {t.name for t in code_graph_tools(".")} == set(_EXPECTED)


def test_tool_schemas_match_contract() -> None:
    tools = {t.name: t for t in code_graph_tools(".")}
    for name, (props, required) in _EXPECTED.items():
        schema = type(tools[name]).input_schema.model_json_schema()
        assert set(schema.get("properties", {})) == props, name
        assert set(schema.get("required", [])) == required, name


def test_every_tool_has_an_llm_description() -> None:
    for t in code_graph_tools("."):
        assert len(t.description) > 40  # written for tool-choice, not a stub
