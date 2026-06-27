"""feat-013 chunk 6: docs are part of the definition of done — the guide exists
and the README links the one-command path."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_guide_exists_and_covers_the_surface() -> None:
    guide = _ROOT / "docs/guides/11-agent-auto-configuration.md"
    assert guide.exists()
    text = guide.read_text()
    for token in ("ckg setup", "--scope", "--hooks", "--undo", "Operational reference"):
        assert token in text


def test_readme_links_the_one_command_path() -> None:
    readme = (_ROOT / "README.md").read_text()
    assert "ckg setup" in readme
    assert "11-agent-auto-configuration.md" in readme
