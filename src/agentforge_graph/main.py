"""Entry point for the ``ckg`` / ``agentforge-graph`` console script.

Dispatches to the CKG command-line interface (``ckg index`` today;
``serve-mcp`` and friends land with feat-008). Engine config is read from
``ckg.yaml``; framework config from ``agentforge.yaml``.
"""

from __future__ import annotations

import sys

from agentforge_graph.cli import main as cli_main


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
