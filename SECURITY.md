# Security Policy

## Supported versions

agentforge-graph is pre-1.0; security fixes land on the **latest released
minor** and are published to PyPI. Older lines are not back-patched — upgrade to
the latest release.

| Version | Supported |
|---|---|
| latest `0.x` | ✅ |
| older | ❌ (upgrade) |

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

Report privately via one of:

- **GitHub Security Advisories** — "Report a vulnerability" on the repository's
  Security tab (preferred; lets us collaborate on a fix before disclosure).
- **Email** — `engg.kjoshi@gmail.com` with a clear subject (`SECURITY:
  agentforge-graph`).

Please include: affected version, a description, reproduction steps or a proof
of concept, and the impact you foresee.

## What to expect

- **Acknowledgement** within a few business days.
- An assessment and, for confirmed issues, a fix on a coordinated timeline. We'll
  keep you updated and credit you in the advisory/CHANGELOG unless you prefer to
  remain anonymous.
- Please give us a reasonable window to release a fix before public disclosure.

## Scope notes

- The deterministic engine runs locally over your code; it makes **no network
  calls** unless you enable a model/DB provider. Treat the **embedded `.ckg/`
  index** like any build artifact (it contains your code's structure).
- The **HTTP MCP transport** is bearer-token authenticated and refuses non-loopback
  binds without a token (ENH-005); do not expose it unauthenticated.
- Model/DB provider credentials are read from the environment — keep them out of
  version control (a gitignored `.env` is the intended pattern).
