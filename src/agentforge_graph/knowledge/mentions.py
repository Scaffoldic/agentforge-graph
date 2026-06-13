"""Extract code mentions from an ADR body and resolve them — precisely — to
graph nodes (feat-010). Only **unambiguous** matches become ``GOVERNS`` edges;
ambiguous or unresolved mentions are counted, never guessed (ADR-0004)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agentforge_graph.core.symbols import normalize_path

_BACKTICK_RE = re.compile(r"`([^`]+)`")
# A qualified name: identifiers joined by '.' or '#', e.g. app.auth.login,
# Auth#login, PaymentService. No spaces, at least one identifier char.
_QUALNAME_RE = re.compile(r"^[A-Za-z_][\w]*(?:[.#][A-Za-z_][\w]*)*$")


@dataclass
class Mentions:
    paths: set[str] = field(default_factory=set)  # normalised repo-relative paths
    names: set[str] = field(default_factory=set)  # bare symbol names (last segment)


def _looks_like_path(token: str, code_exts: set[str]) -> bool:
    return "/" in token and any(token.endswith(ext) for ext in code_exts)


def _leaf_name(qualname: str) -> str:
    return re.split(r"[.#]", qualname.strip())[-1]


def extract_mentions(body: str, code_exts: set[str]) -> Mentions:
    m = Mentions()
    # backtick code spans: paths or qualified names
    for span in _BACKTICK_RE.findall(body):
        token = span.strip()
        if _looks_like_path(token, code_exts):
            m.paths.add(normalize_path(token))
        elif _QUALNAME_RE.match(token):
            m.names.add(_leaf_name(token))
    # bare path-like tokens anywhere (e.g. mentioned in prose without backticks)
    ext_alt = "|".join(re.escape(e.lstrip(".")) for e in sorted(code_exts))
    if ext_alt:
        for token in re.findall(rf"[\w./-]+\.(?:{ext_alt})\b", body):
            if "/" in token:
                m.paths.add(normalize_path(token))
    return m


def resolve_mentions(
    mentions: Mentions,
    path_index: dict[str, str],
    name_index: dict[str, list[str]],
) -> tuple[set[str], int]:
    """Map mentions to node ids. Returns (resolved target ids, unresolved count).
    A path → its FILE id (exact). A name → its symbol id **iff unique**."""
    targets: set[str] = set()
    unresolved = 0
    for path in mentions.paths:
        file_id = path_index.get(path)
        if file_id is not None:
            targets.add(file_id)
        else:
            unresolved += 1
    for name in mentions.names:
        candidates = name_index.get(name, [])
        if len(candidates) == 1:
            targets.add(candidates[0])
        else:
            unresolved += 1  # 0 (unknown) or >1 (ambiguous) — never guess
    return targets, unresolved
