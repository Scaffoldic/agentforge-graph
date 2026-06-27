"""feat-013 setup errors. A single typed error so the CLI can print an
actionable message instead of a stack trace."""

from __future__ import annotations


class SetupError(Exception):
    """A recoverable ``ckg setup`` failure (bad config target, parse failure,
    bind-safety refusal, write conflict). The CLI renders the message and exits
    non-zero."""
