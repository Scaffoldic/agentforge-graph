"""ENH-022: workspace-level config cascade.

A `defaults:` block in workspace.yaml (or a sibling ckg.yaml) supplies config
every member inherits, with deterministic per-member override. Resolution order
(lowest → highest): sibling ckg.yaml → manifest defaults → member inline blocks →
member `config:` file.
"""

from __future__ import annotations

from pathlib import Path

from agentforge_graph.config import EmbedConfig, StoreConfig
from agentforge_graph.serve.workspace import WorkspaceConfig, member_overrides


def _ws(tmp_path: Path, body: str) -> WorkspaceConfig:
    p = tmp_path / "workspace.yaml"
    p.write_text(body)
    return WorkspaceConfig.load(p)


def test_defaults_apply_to_members_without_own_config(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        """
workspace: org
defaults:
  store:
    central_root: /shared/ckg
  embed:
    driver: openai
members:
  - name: web
    repo: ./web
""",
    )
    rc = ws.resolve_member_config(ws.members[0])
    assert StoreConfig.load(rc).central_root == "/shared/ckg"
    assert EmbedConfig.load(rc).driver == "openai"


def test_member_inline_block_overrides_defaults(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        """
defaults:
  store:
    central_root: /shared/ckg
  embed:
    driver: openai
members:
  - name: web
    repo: ./web
    embed:
      driver: fake
""",
    )
    rc = ws.resolve_member_config(ws.members[0])
    assert EmbedConfig.load(rc).driver == "fake"  # member inline wins
    assert StoreConfig.load(rc).central_root == "/shared/ckg"  # default still applies


def test_member_config_file_wins_over_everything(tmp_path: Path) -> None:
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "ckg.yaml").write_text("embed:\n  driver: bedrock\n")
    ws = _ws(
        tmp_path,
        """
defaults:
  embed:
    driver: openai
members:
  - name: web
    repo: ./web
    config: ./web/ckg.yaml
    embed:
      driver: fake
""",
    )
    rc = ws.resolve_member_config(ws.members[0])
    assert EmbedConfig.load(rc).driver == "bedrock"  # member file is highest precedence


def test_manifest_defaults_win_over_sibling_ckg_yaml(tmp_path: Path) -> None:
    # sibling ckg.yaml next to workspace.yaml = fallback defaults
    (tmp_path / "ckg.yaml").write_text("store:\n  path: from_sibling\nembed:\n  driver: openai\n")
    ws = _ws(
        tmp_path,
        """
defaults:
  embed:
    driver: fake
members:
  - name: web
    repo: ./web
""",
    )
    rc = ws.resolve_member_config(ws.members[0])
    assert EmbedConfig.load(rc).driver == "fake"  # manifest defaults win
    assert StoreConfig.load(rc).path == "from_sibling"  # sibling-only block still applies


def test_member_overrides_ignores_scalars_and_unknown_keys(tmp_path: Path) -> None:
    ws = _ws(
        tmp_path,
        """
members:
  - name: web
    repo: ./web
    embed: false
    bogus:
      x: 1
    store:
      path: ok
""",
    )
    ov = member_overrides(ws.members[0])
    assert ov == {"store": {"path": "ok"}}  # scalar embed + unknown 'bogus' dropped


def test_no_defaults_yields_empty_section(tmp_path: Path) -> None:
    ws = _ws(tmp_path, "members:\n  - name: web\n    repo: ./web\n")
    rc = ws.resolve_member_config(ws.members[0])
    assert rc.section == {}
    assert EmbedConfig.load(rc).driver == EmbedConfig().driver  # built-in defaults
