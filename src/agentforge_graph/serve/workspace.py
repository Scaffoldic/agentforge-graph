"""Workspace manifest — the member services a federated MCP server spans
(ENH-020).

A ``workspace.yaml`` lists the repos/services to serve from one endpoint:

    workspace: acme-platform
    members:
      - name: gateway
        repo: ./gateway
      - name: orders
        repo: ./services/orders
      - name: payments
        repo: ./services/payments
        config: ./services/payments/ckg.yaml   # optional per-member config

Each member resolves to one engine; a federation-aware tool fans across them.
Member ``repo`` paths are resolved relative to the manifest's directory. An
optional per-member ``config`` overrides config discovery for that member.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class WorkspaceMember(BaseModel):
    name: str
    repo: str
    config: str | None = None

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("workspace member name must be non-empty")
        return v


class WorkspaceConfig(BaseModel):
    workspace: str = "workspace"
    members: list[WorkspaceMember] = Field(default_factory=list)
    # the manifest's directory — member repo/config paths resolve against it
    base_dir: Path = Field(default_factory=Path)

    @classmethod
    def load(cls, path: str | Path) -> WorkspaceConfig:
        p = Path(path)
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{p}: workspace manifest must be a mapping")
        members = data.get("members") or []
        if not members:
            raise ValueError(f"{p}: workspace manifest has no members")
        cfg = cls(
            workspace=str(data.get("workspace", "workspace")),
            members=[WorkspaceMember(**m) for m in members],
            base_dir=p.resolve().parent,
        )
        names = [m.name for m in cfg.members]
        if len(set(names)) != len(names):
            raise ValueError(f"{p}: duplicate member names {names}")
        return cfg

    def member_repo(self, m: WorkspaceMember) -> Path:
        """The member's repo path, resolved against the manifest directory."""
        repo = Path(m.repo)
        return repo if repo.is_absolute() else (self.base_dir / repo)

    def member_config(self, m: WorkspaceMember) -> str | None:
        if m.config is None:
            return None
        cfg = Path(m.config)
        return str(cfg if cfg.is_absolute() else (self.base_dir / cfg))
