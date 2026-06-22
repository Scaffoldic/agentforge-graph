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
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentforge_graph.config import ResolvedConfig, _section_of, block_keys


class WorkspaceMember(BaseModel):
    # ENH-022: allow inline engine-config block overrides (`store:`/`embed:`/…)
    # on a member entry — captured in `model_extra`, surfaced by member_overrides.
    model_config = ConfigDict(extra="allow")

    name: str
    repo: str
    config: str | None = None

    @field_validator("name")
    @classmethod
    def _name_nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("workspace member name must be non-empty")
        return v


def member_overrides(m: WorkspaceMember) -> dict[str, Any]:
    """The member's inline engine-config block overrides (ENH-022): the subset of
    its extra manifest fields whose key is a recognized config block
    (``store``/``embed``/…) and whose value is a mapping. Non-block extras and
    shorthand scalars (e.g. ENH-023's ``embed: false``) are ignored here."""
    extra = m.model_extra or {}
    keys = block_keys()
    return {k: v for k, v in extra.items() if k in keys and isinstance(v, dict)}


def _merge_blocks(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Per-block **shallow** merge: a block present in ``src`` fully replaces the
    same block in ``dst`` (no deep key-merge — predictable, matches the block
    model)."""
    if not isinstance(src, dict):
        return
    for k, v in src.items():
        dst[k] = v


class WorkspaceConfig(BaseModel):
    workspace: str = "workspace"
    members: list[WorkspaceMember] = Field(default_factory=list)
    # the manifest's directory — member repo/config paths resolve against it
    base_dir: Path = Field(default_factory=Path)
    # ENH-022: org-wide config defaults every member inherits (from the manifest's
    # `defaults:` block), and the fallback defaults read from a sibling `ckg.yaml`
    # next to the manifest. `defaults` wins over `sibling_defaults`.
    defaults: dict[str, Any] = Field(default_factory=dict)
    sibling_defaults: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> WorkspaceConfig:
        p = Path(path)
        data = yaml.safe_load(p.read_text()) or {}
        if not isinstance(data, dict):
            raise ValueError(f"{p}: workspace manifest must be a mapping")
        members = data.get("members") or []
        if not members:
            raise ValueError(f"{p}: workspace manifest has no members")
        base_dir = p.resolve().parent
        raw_defaults = data.get("defaults")
        sibling = base_dir / "ckg.yaml"
        cfg = cls(
            workspace=str(data.get("workspace", "workspace")),
            members=[WorkspaceMember(**m) for m in members],
            base_dir=base_dir,
            defaults=raw_defaults if isinstance(raw_defaults, dict) else {},
            sibling_defaults=_section_of(sibling) if sibling.is_file() else {},
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

    def resolve_member_config(self, m: WorkspaceMember) -> ResolvedConfig:
        """The member's effective engine config (ENH-022) as a drop-in
        :class:`ResolvedConfig`. Layers, lowest → highest precedence:

        1. sibling ``ckg.yaml`` next to the manifest (fallback defaults),
        2. the manifest's ``defaults:`` block (org-wide),
        3. the member's inline block overrides,
        4. the member's explicit ``config:`` file.

        Merge is per-block shallow (a later source replaces a whole block)."""
        section: dict[str, Any] = {}
        _merge_blocks(section, self.sibling_defaults)
        _merge_blocks(section, self.defaults)
        _merge_blocks(section, member_overrides(m))
        # ENH-023: per-member `embed: true|false` shorthand → embed.enabled. Same
        # (member-inline) precedence tier as block overrides; a member `config:`
        # file can still override it below.
        embed_flag = (m.model_extra or {}).get("embed")
        if isinstance(embed_flag, bool):
            block = section.get("embed")
            section["embed"] = {**(block if isinstance(block, dict) else {}), "enabled": embed_flag}
        mc = self.member_config(m)
        if mc and Path(mc).is_file():
            _merge_blocks(section, _section_of(Path(mc)))
        return ResolvedConfig(section=section, origin=f"workspace:{self.workspace}:{m.name}")
