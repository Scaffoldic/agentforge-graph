"""Rails pack golden tests (ENH-012): the explicit routes.rb declarations, the
controller#action → CamelController convention, root, and conservative handling
of resourceful/nested DSL — on FrameworkFacts."""

from __future__ import annotations

import hashlib

from agentforge_graph.core import NodeKind, SourceFile
from agentforge_graph.frameworks.base import FrameworkFacts, FrameworkPack
from agentforge_graph.frameworks.packs.rails import RAILS_PACK


def _src(body: str) -> SourceFile:
    text = "Rails.application.routes.draw do\n" + body + "end\n"
    return SourceFile(
        path="config/routes.rb",
        text=text,
        language="rb",
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
    )


def _facts(body: str) -> FrameworkFacts:
    return RAILS_PACK.extract(_src(body), repo="fixture", commit="c0")


def test_pack_is_a_framework_pack() -> None:
    assert isinstance(RAILS_PACK, FrameworkPack)
    assert RAILS_PACK.name == "rails"
    assert RAILS_PACK.language == "ruby" and RAILS_PACK.language_slug == "rb"


def test_detect_via_import_marker() -> None:
    assert RAILS_PACK.detect(set(), "Rails.application.routes.draw do\nend") is True
    assert RAILS_PACK.detect(set(), "puts 'hi'") is False


def test_hashrocket_form() -> None:
    facts = _facts('  get "/users" => "users#index"\n')
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.name == "GET /users"
    assert route.attrs["handler_class"] == "UsersController"
    assert route.attrs["handler_method"] == "index"
    assert route.attrs["handler"] == ""  # grounded cross-file by pass-2


def test_to_keyword_form_and_camelize() -> None:
    facts = _facts('  post "/profiles", to: "user_profiles#create"\n')
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["method"] == "POST"
    assert route.attrs["handler_class"] == "UserProfilesController"  # snake -> Camel
    assert route.attrs["handler_method"] == "create"


def test_root_maps_to_get_slash() -> None:
    facts = _facts('  root "home#index"\n')
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["method"] == "GET" and route.attrs["path"] == "/"
    assert route.attrs["handler_class"] == "HomeController"


def test_namespaced_controller_uses_last_segment() -> None:
    facts = _facts('  get "/admin/users" => "admin/users#index"\n')
    route = next(n for n in facts.nodes if n.kind is NodeKind.ROUTE)
    assert route.attrs["handler_class"] == "UsersController"


def test_resources_counted_not_expanded() -> None:
    facts = _facts("  resources :photos\n")
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []
    assert facts.unresolved == 1  # resourceful DSL — counted, a follow-up


def test_verb_outside_draw_block_ignored() -> None:
    # a `get` call that is not inside routes.draw is not a route
    sf = SourceFile(
        path="other.rb",
        text='get "/x" => "y#z"\n',
        language="rb",
        content_hash=hashlib.sha256(b"x").hexdigest(),
    )
    facts = RAILS_PACK.extract(sf, repo="fixture", commit="c0")
    assert [n for n in facts.nodes if n.kind is NodeKind.ROUTE] == []
