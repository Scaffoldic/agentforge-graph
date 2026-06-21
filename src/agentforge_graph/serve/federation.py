"""Federated engine — one handle over many member engines (ENH-020, C-lite).

Holds an ``_Engine`` per workspace member and presents the same ``targets`` /
``one`` selector the single ``_Engine`` does, so the read-only tools fan across
the whole org from one MCP endpoint:

- **survey tools** (search / routes / decisions / status) call ``targets(service)``
  and merge, tagging each result with its ``service``;
- **pinpoint tools** (symbol / impact / neighbors / explain / history / repo_map)
  call ``one(service)`` to operate on a single member.

``service`` selects a member by name; omitting it fans (survey) or, for a
pinpoint tool with more than one member, raises asking which service.
"""

from __future__ import annotations

import re
from typing import Any

from .engine import TOOL_API_VERSION, _Engine
from .workspace import WorkspaceConfig


class MemberNotFound(ValueError):
    """A tool named a ``service`` that is not a workspace member."""


class AmbiguousMember(ValueError):
    """A pinpoint tool was called with no ``service`` but several members exist."""


class FederatedEngine:
    def __init__(self, members: dict[str, _Engine]) -> None:
        if not members:
            raise ValueError("a federated engine needs at least one member")
        self.members = members

    @classmethod
    def from_workspace(cls, ws: WorkspaceConfig) -> FederatedEngine:
        members = {m.name: _Engine(str(ws.member_repo(m)), ws.member_config(m)) for m in ws.members}
        return cls(members)

    def _require(self, service: str) -> _Engine:
        if service not in self.members:
            raise MemberNotFound(
                f"unknown service {service!r}; members: {', '.join(sorted(self.members))}"
            )
        return self.members[service]

    def targets(self, service: str = "") -> list[tuple[str, _Engine]]:
        """The engines a survey tool fans across — one named member when
        ``service`` is given, else every member (each tagged with its name)."""
        if service:
            return [(service, self._require(service))]
        return list(self.members.items())

    def one(self, service: str = "") -> _Engine:
        """The single engine a pinpoint tool operates on. Requires ``service``
        when more than one member exists (a symbol id belongs to one repo)."""
        if service:
            return self._require(service)
        if len(self.members) == 1:
            return next(iter(self.members.values()))
        raise AmbiguousMember(
            "this tool targets one service; pass service=<one of "
            f"{', '.join(sorted(self.members))}>"
        )

    async def service_map(self) -> dict[str, Any]:
        """The org's cross-service call graph (ENH-020 C-full): match each
        member's outbound ``ServiceCall`` to a ``Route`` in **another** member by
        ``(method, path)`` and return the resolved edges. Computed live because
        member graphs are separate stores. Unique-match-only (ADR-0004): a call
        that matches routes in several services is left unresolved, never guessed.
        """
        routes: dict[str, list[tuple[str, re.Pattern[str], Any]]] = {}
        calls: dict[str, list[Any]] = {}
        for name, eng in self.members.items():
            cg = await eng.code_graph()
            routes[name] = [
                (r.method, _compile_route(r.path_pattern or r.path), r) for r in await cg.routes()
            ]
            calls[name] = await cg.service_calls()

        edges: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for caller, call_list in calls.items():
            for c in call_list:
                matches = [
                    (provider, r)
                    for provider, rlist in routes.items()
                    if provider != caller  # cross-service only
                    for (method, rx, r) in rlist
                    if method == c.method and rx.match(c.path)
                ]
                if len(matches) == 1:
                    provider, r = matches[0]
                    edges.append(
                        {
                            "from_service": caller,
                            "to_service": provider,
                            "method": c.method,
                            "call_path": c.path,
                            "url": c.url,
                            "caller": f"{c.file}:{c.line}",
                            "route_path": r.path_pattern or r.path,
                            "handler": r.handler,
                        }
                    )
                else:
                    unresolved.append(
                        {
                            "from_service": caller,
                            "method": c.method,
                            "path": c.path,
                            "reason": "ambiguous (matches several services)"
                            if matches
                            else "no matching route in any service",
                        }
                    )
        edges.sort(key=lambda e: (e["from_service"], e["to_service"], e["call_path"]))
        return {
            "edges": edges,
            "edge_count": len(edges),
            "unresolved": unresolved,
            "services": sorted(self.members),
            "tool_api_version": TOOL_API_VERSION,
        }

    async def close(self) -> None:
        for eng in self.members.values():
            await eng.close()


def _compile_route(pattern: str) -> re.Pattern[str]:
    """A route path pattern → a regex matching concrete call paths. Path
    parameters in any framework dialect — ``{id}`` (FastAPI), ``:id`` (Express),
    ``<id>`` (Flask/Django) — match a single path segment."""
    body = pattern.strip("/")
    if not body:
        return re.compile("^/?$")
    segs = []
    for seg in body.split("/"):
        is_param = (
            (seg.startswith("{") and seg.endswith("}"))
            or seg.startswith(":")
            or (seg.startswith("<") and seg.endswith(">"))
        )
        segs.append(r"[^/]+" if is_param else re.escape(seg))
    return re.compile("^/" + "/".join(segs) + "/?$")
