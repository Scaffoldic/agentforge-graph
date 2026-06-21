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

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .engine import TOOL_API_VERSION, _Engine
from .workspace import WorkspaceConfig

_HTTP_METHODS = {"get", "post", "put", "delete", "patch", "options", "head"}
# OpenAPI / Swagger spec files looked for at a member's repo root (ENH-020).
_OPENAPI_NAMES = ("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml")


@dataclass(frozen=True)
class _RouteMatcher:
    """A route a service call can match against — from a framework extraction or
    an OpenAPI spec, normalised to one shape."""

    method: str
    regex: re.Pattern[str]
    path: str
    handler: str
    source: str  # "framework" | "openapi"


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
        routes: dict[str, list[_RouteMatcher]] = {}
        calls: dict[str, list[Any]] = {}
        for name, eng in self.members.items():
            routes[name] = await self._member_routes(eng)
            calls[name] = await (await eng.code_graph()).service_calls()

        edges: list[dict[str, Any]] = []
        unresolved: list[dict[str, Any]] = []
        for caller, call_list in calls.items():
            for c in call_list:
                matches = [
                    (provider, rm)
                    for provider, rlist in routes.items()
                    if provider != caller  # cross-service only
                    for rm in rlist
                    if rm.method == c.method and rm.regex.match(c.path)
                ]
                if len(matches) == 1:
                    provider, rm = matches[0]
                    edges.append(
                        {
                            "from_service": caller,
                            "to_service": provider,
                            "method": c.method,
                            "call_path": c.path,
                            "url": c.url,
                            "caller": f"{c.file}:{c.line}",
                            "route_path": rm.path,
                            "handler": rm.handler,
                            "via": rm.source,  # framework | openapi
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

    async def _member_routes(self, eng: _Engine) -> list[_RouteMatcher]:
        """A member's routes for matching: framework-extracted routes first, then
        OpenAPI-declared routes that fill gaps. Deduped by (method, param-agnostic
        path) so a framework route and its spec twin don't make every call
        ambiguous — and so contract-first services (spec only, no detected
        framework) are still matched."""
        seen: set[tuple[str, str]] = set()
        out: list[_RouteMatcher] = []
        cg = await eng.code_graph()
        for r in await cg.routes():
            path = r.path_pattern or r.path
            key = (r.method, _normalize_template(path))
            if key in seen:
                continue
            seen.add(key)
            out.append(_RouteMatcher(r.method, _compile_route(path), path, r.handler, "framework"))
        for method, path, op_id in _openapi_routes(Path(eng.repo_path)):
            key = (method, _normalize_template(path))
            if key in seen:
                continue
            seen.add(key)
            out.append(_RouteMatcher(method, _compile_route(path), path, op_id, "openapi"))
        return out

    async def trace(
        self, service: str, depth: int = 10, direction: str = "downstream"
    ) -> dict[str, Any]:
        """Walk the cross-service call graph from ``service`` (ENH-020 C-full):
        ``downstream`` follows the services it calls (data flow), ``upstream``
        follows the services that call it (blast radius), to ``depth`` hops.
        Returns the reachable hops (each annotated with its hop number) and the
        set of services reached. Cycles terminate (a service is expanded once).
        """
        self._require(service)
        if direction not in ("downstream", "upstream"):
            raise ValueError(f"direction must be 'downstream' or 'upstream', got {direction!r}")
        edges = (await self.service_map())["edges"]
        upstream = direction == "upstream"
        adj: dict[str, list[dict[str, Any]]] = {}
        for e in edges:
            adj.setdefault(e["to_service"] if upstream else e["from_service"], []).append(e)

        visited = {service}
        frontier = [service]
        seen_edge: set[tuple[str, str, str, str]] = set()
        hops: list[dict[str, Any]] = []
        hop_no = 0
        while frontier and hop_no < min(depth, 50):
            hop_no += 1
            nxt: list[str] = []
            for s in frontier:
                for e in adj.get(s, []):
                    key = (e["from_service"], e["to_service"], e["method"], e["call_path"])
                    if key not in seen_edge:
                        seen_edge.add(key)
                        hops.append({**e, "hop": hop_no})
                    target = e["from_service"] if upstream else e["to_service"]
                    if target not in visited:
                        visited.add(target)
                        nxt.append(target)
            frontier = nxt
        return {
            "start": service,
            "direction": direction,
            "reached": sorted(visited - {service}),
            "hops": hops,
            "hop_count": len(hops),
            "tool_api_version": TOOL_API_VERSION,
        }

    async def close(self) -> None:
        for eng in self.members.values():
            await eng.close()


def _normalize_template(path: str) -> str:
    """A path template with every parameter segment collapsed to ``{}`` — so
    ``/v1/orders/{oid}``, ``/v1/orders/:id`` and ``/v1/orders/{id}`` compare equal
    (used to dedupe a framework route against its OpenAPI twin)."""
    segs = []
    for seg in path.strip("/").split("/"):
        is_param = (
            (seg.startswith("{") and seg.endswith("}"))
            or seg.startswith(":")
            or (seg.startswith("<") and seg.endswith(">"))
        )
        segs.append("{}" if is_param else seg)
    return "/" + "/".join(segs)


def _openapi_routes(repo_path: Path) -> list[tuple[str, str, str]]:
    """`(METHOD, path, operationId)` for every operation in a member's OpenAPI /
    Swagger spec (the first one found at the repo root), or ``[]`` when there is
    none or it can't be parsed. Anchors the route side to the declared contract —
    authoritative paths, and coverage for contract-first services with no detected
    framework (ENH-020 C-full precision upgrade)."""
    spec = None
    for name in _OPENAPI_NAMES:
        f = repo_path / name
        if f.is_file():
            try:
                spec = yaml.safe_load(f.read_text())  # YAML is a JSON superset
            except (yaml.YAMLError, json.JSONDecodeError, OSError):
                return []
            break
    if not isinstance(spec, dict):
        return []
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return []
    out: list[tuple[str, str, str]] = []
    for path, ops in paths.items():
        if not isinstance(path, str) or not isinstance(ops, dict):
            continue
        for method, op in ops.items():
            if method.lower() not in _HTTP_METHODS:
                continue
            op_id = op.get("operationId", "") if isinstance(op, dict) else ""
            out.append((method.upper(), path, str(op_id)))
    return out


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
