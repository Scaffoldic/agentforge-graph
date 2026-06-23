"""Symbol identity — stable, human-readable, deterministic node IDs.

A symbol ID is a single string derived from
``(scheme, lang, repo, path, descriptor)``. It has no global counters
and no ordering constraints, so per-file extraction can run in any order
and merge, and the same symbol keeps its ID across commits — the
property incremental indexing (feat-004) and history (feat-009) depend
on. The descriptor grammar is descriptor-based, deterministic. See ADR-0003 and
``docs/design/design-001-core-contracts-module.md`` §4.4.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

SCHEME = "ckg"
_FIELD_SEP = " "


def _encode(field: str) -> str:
    """Escape the field separator and the escape char so IDs round-trip."""
    return field.replace("%", "%25").replace(_FIELD_SEP, "%20")


def _decode(field: str) -> str:
    # %20 before %25 so an escaped escape (%2520) decodes back to "%20".
    return field.replace("%20", _FIELD_SEP).replace("%25", "%")


def normalize_path(path: str) -> str:
    """Repo-relative, posix-separated, no leading ``./`` or ``/``.

    Ensures the same file yields the same ID on any OS.
    """
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


class ParsedSymbol(BaseModel):
    """The structured form of a symbol ID."""

    model_config = ConfigDict(frozen=True)

    scheme: str
    lang: str
    repo: str
    path: str
    descriptor: str


class SymbolID:
    """Format and parse symbol-ID strings. Stateless."""

    SCHEME = SCHEME

    @staticmethod
    def for_symbol(lang: str, repo: str, path: str, descriptor: str) -> str:
        parts = [SCHEME, lang, repo, normalize_path(path), descriptor]
        return _FIELD_SEP.join(_encode(p) for p in parts)

    @staticmethod
    def parse(symbol_id: str) -> ParsedSymbol:
        raw = symbol_id.split(_FIELD_SEP)
        if len(raw) != 5:
            raise ValueError(
                f"malformed symbol id (expected 5 space-separated fields): {symbol_id!r}"
            )
        scheme, lang, repo, path, descriptor = (_decode(p) for p in raw)
        if scheme != SCHEME:
            raise ValueError(f"unknown symbol-id scheme {scheme!r} (expected {SCHEME!r})")
        return ParsedSymbol(scheme=scheme, lang=lang, repo=repo, path=path, descriptor=descriptor)


class Descriptor:
    """Builders for the descriptor segments.

    Segments compose by concatenation — a method on a class is
    ``Descriptor.type("Auth") + Descriptor.method("login")`` →
    ``"Auth#login()."``. Language packs (feat-002) map AST nodes to
    these; core only owns the string format.
    """

    @staticmethod
    def namespace(name: str) -> str:
        return f"{name}/"

    @staticmethod
    def type(name: str) -> str:
        return f"{name}#"

    @staticmethod
    def term(name: str) -> str:
        return f"{name}."

    @staticmethod
    def method(name: str, disambiguator: int = 0) -> str:
        """A method/function. ``disambiguator`` n>=1 marks the nth overload."""
        if disambiguator < 0:
            raise ValueError("disambiguator must be >= 0")
        suffix = f"(+{disambiguator})" if disambiguator else ""
        return f"{name}{suffix}()."

    @staticmethod
    def local(seed: str) -> str:
        """Descriptor for an anonymous/local symbol with no stable name.

        ``seed`` should be derived from the symbol's position within its
        nearest *named* ancestor so edits above the ancestor don't shift
        it. Inherently less stable than named symbols (ADR-0003 §risks).
        """
        digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:8]
        return f"local({digest})"
