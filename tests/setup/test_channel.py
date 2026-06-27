"""feat-013 / FA-001 P1: best-effort install-channel detection."""

from __future__ import annotations

import pytest

from agentforge_graph.setup.channel import detect_channel


@pytest.mark.parametrize(
    ("prefix", "expected"),
    [
        ("/Users/me/.local/share/uv/tools/agentforge-graph", "uvx"),
        ("/home/me/.cache/uv/archive-v0/abc123", "uvx"),
        ("/home/me/.local/pipx/venvs/agentforge-graph", "pipx"),
        ("/home/me/project/.venv", "pip"),
        ("/usr/local", "pip"),
    ],
)
def test_detect_channel(prefix: str, expected: str) -> None:
    assert detect_channel(prefix=prefix, executable=prefix + "/bin/python") == expected


def test_windows_paths_normalized() -> None:
    assert detect_channel(prefix=r"C:\Users\me\pipx\venvs\x", executable="py") == "pipx"
