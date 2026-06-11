from __future__ import annotations

import pytest

from agentforge_graph.core import Descriptor, ParsedSymbol, SymbolID, normalize_path

# Tricky field values: spaces, the escape char, unicode, separators.
_TRICKY = [
    ("py", "repo", "src/app/auth.py", "Auth#login()."),
    ("ts", "my repo", "src/a b/c.ts", "Foo#bar()."),
    ("go", "repo", "pkg/100%/x.go", "do."),
    ("rb", "repo", "lib/café.rb", "Café#méthode()."),
    ("py", "r", "p.py", ""),  # empty descriptor (a File node)
]


@pytest.mark.parametrize(("lang", "repo", "path", "desc"), _TRICKY)
def test_round_trips(lang: str, repo: str, path: str, desc: str) -> None:
    sid = SymbolID.for_symbol(lang, repo, path, desc)
    parsed = SymbolID.parse(sid)
    assert parsed == ParsedSymbol(
        scheme="ckg", lang=lang, repo=repo, path=normalize_path(path), descriptor=desc
    )
    # re-formatting the parsed pieces yields the identical id
    assert SymbolID.for_symbol(parsed.lang, parsed.repo, parsed.path, parsed.descriptor) == sid


def test_deterministic_and_order_independent() -> None:
    a = SymbolID.for_symbol("py", "repo", "a.py", "f().")
    b = SymbolID.for_symbol("py", "repo", "a.py", "f().")
    assert a == b


def test_path_normalized_across_os() -> None:
    win = SymbolID.for_symbol("py", "repo", ".\\src\\a.py", "f().")
    nix = SymbolID.for_symbol("py", "repo", "src/a.py", "f().")
    assert win == nix


def test_malformed_id_rejected() -> None:
    with pytest.raises(ValueError, match="malformed"):
        SymbolID.parse("not a valid symbol id with too many fields here")


def test_unknown_scheme_rejected() -> None:
    bad = SymbolID.for_symbol("py", "repo", "a.py", "f().").replace("ckg", "zzz", 1)
    with pytest.raises(ValueError, match="scheme"):
        SymbolID.parse(bad)


def test_descriptor_builders() -> None:
    assert Descriptor.type("Auth") == "Auth#"
    assert Descriptor.term("MAX") == "MAX."
    assert Descriptor.namespace("app") == "app/"
    assert Descriptor.method("login") == "login()."
    assert Descriptor.method("login", 1) == "login(+1)()."
    assert Descriptor.type("Auth") + Descriptor.method("login") == "Auth#login()."


def test_local_descriptor_is_deterministic_and_distinct() -> None:
    assert Descriptor.local("seedA") == Descriptor.local("seedA")
    assert Descriptor.local("seedA") != Descriptor.local("seedB")
    assert Descriptor.local("seedA").startswith("local(")


def test_method_negative_disambiguator_rejected() -> None:
    with pytest.raises(ValueError, match="disambiguator"):
        Descriptor.method("x", -1)
