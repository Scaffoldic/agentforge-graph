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

from .engine import _Engine
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

    async def close(self) -> None:
        for eng in self.members.values():
            await eng.close()
