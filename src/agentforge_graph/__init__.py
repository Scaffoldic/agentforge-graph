"""agentforge-graph: a Code Knowledge Graph (CKG) engine + agent toolset."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from agentforge_graph.cli import main

try:
    __version__ = _pkg_version("agentforge-graph")
except PackageNotFoundError:  # a source checkout without installed dist metadata
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "main"]
