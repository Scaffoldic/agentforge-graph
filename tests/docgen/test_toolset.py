"""feat-016 chunk 3: provenance capture from tool observations (the floor)."""

from __future__ import annotations

import json

from agentforge_graph.core import NodeKind, Source, SymbolID
from agentforge_graph.docgen.toolset import capture_refs

_ID_A = SymbolID.for_symbol("py", "repo", "app.py", "Repo#")
_ID_B = SymbolID.for_symbol("py", "repo", "app.py", "save().")
_ID_LLM = SymbolID.for_symbol("summary", "repo", "app.py", "summary.")


def _search_obs() -> str:
    # mimics ckg_search / ckg_symbol ContextPack.to_dict() JSON
    return json.dumps(
        {
            "items": [
                {
                    "id": _ID_A,
                    "kind": NodeKind.CLASS.value,
                    "name": "Repo",
                    "path": "app.py",
                    "span": [1, 9],
                    "provenance": Source.PARSED.value,
                },
                {
                    "id": _ID_B,
                    "kind": NodeKind.METHOD.value,
                    "name": "save",
                    "path": "app.py",
                    "span": [3, 5],
                    "provenance": Source.RESOLVED.value,
                },
                {
                    "id": _ID_LLM,
                    "kind": NodeKind.SUMMARY.value,
                    "name": "summary:app.py",
                    "provenance": Source.LLM.value,  # must be dropped (echo-chamber floor)
                },
            ],
            "indexed_commit": "abc",
        }
    )


def test_capture_extracts_parsed_and_resolved() -> None:
    refs = capture_refs([_search_obs()])
    assert set(refs) == {_ID_A, _ID_B}  # llm item dropped
    assert refs[_ID_A].kind is NodeKind.CLASS
    assert refs[_ID_A].name == "Repo"
    assert refs[_ID_A].span == (1, 9)
    assert refs[_ID_B].path == "app.py"


def test_capture_drops_llm_provenance() -> None:
    refs = capture_refs([_search_obs()])
    assert _ID_LLM not in refs  # anti-echo-chamber: llm fact never citable


def test_capture_skips_non_json_and_malformed() -> None:
    assert capture_refs(["not json at all", "# repo map text\nfoo bar"]) == {}
    # a dict without a valid symbol id contributes nothing
    assert capture_refs([json.dumps({"items": [{"id": "not-a-symbol", "kind": "Class"}]})]) == {}


def test_capture_skips_item_without_kind() -> None:
    obs = json.dumps({"items": [{"id": _ID_A, "name": "Repo", "provenance": "parsed"}]})
    assert capture_refs([obs]) == {}  # no kind → cannot build a typed ref


def test_capture_dedupes_across_observations() -> None:
    refs = capture_refs([_search_obs(), _search_obs()])
    assert set(refs) == {_ID_A, _ID_B}
