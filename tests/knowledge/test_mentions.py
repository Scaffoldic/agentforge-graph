"""Mention extraction + precise resolution (feat-010): paths, qualified names,
and the critical negative — ambiguous mentions must NOT link."""

from __future__ import annotations

from agentforge_graph.knowledge.mentions import extract_mentions, resolve_mentions

EXTS = {".py", ".ts"}


def test_extract_backtick_path_and_qualified_name() -> None:
    body = "See `src/app/auth.py` and the `PaymentService` class and `app.auth.login`."
    m = extract_mentions(body, EXTS)
    assert "src/app/auth.py" in m.paths
    assert "PaymentService" in m.names
    assert "login" in m.names  # leaf of a dotted name


def test_extract_bare_path() -> None:
    m = extract_mentions("the file src/app/payments.py handles it", EXTS)
    assert "src/app/payments.py" in m.paths


def test_extract_ignores_non_code() -> None:
    m = extract_mentions("read `README` and `the docs`", EXTS)
    assert m.paths == set()
    assert m.names == {"README"}  # a lone identifier-like token; resolves only if unique


def test_resolve_path_and_unique_name() -> None:
    m = extract_mentions("`src/app/payments.py` and `PaymentService`", EXTS)
    path_index = {"src/app/payments.py": "FILE_ID"}
    name_index = {"PaymentService": ["SVC_ID"]}
    targets, unresolved = resolve_mentions(m, path_index, name_index)
    assert targets == {"FILE_ID", "SVC_ID"}
    assert unresolved == 0


def test_ambiguous_name_does_not_link() -> None:
    m = extract_mentions("`handle` is everywhere", EXTS)
    name_index = {"handle": ["A", "B"]}  # two candidates → ambiguous
    targets, unresolved = resolve_mentions(m, {}, name_index)
    assert targets == set()
    assert unresolved == 1


def test_unknown_mentions_counted() -> None:
    m = extract_mentions("`src/missing.py` and `Nonexistent`", EXTS)
    targets, unresolved = resolve_mentions(m, {}, {})
    assert targets == set()
    assert unresolved == 2
