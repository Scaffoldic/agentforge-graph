# ENH-005: AuthN/AuthZ for the HTTP MCP transport

| Field | Value |
|---|---|
| **ID** | ENH-005 |
| **Value/Impact** | High (blocks any *remote*/multi-tenant HTTP deployment) |
| **Effort** | M |
| **Status** | **done** (2026-06-15) |
| **Area** | `serve` (feat-008 HTTP transport) |
| **Relates to** | feat-008 (MCP server); follows the HTTP transport (PR #22) |

## Motivation

feat-008 now serves the CKG over **streamable-HTTP** (`ckg serve-mcp
--transport http`, mounted at `/mcp`). The HTTP server has **no built-in
authentication or authorization** at 0.1 — anyone who can reach the port can call
every tool and read the whole graph. That is fine for the intended 0.1 use
(localhost / a trusted container, one repo per process), but it **blocks any
remote or shared deployment** without an external proxy.

This is the gap to close before the CKG is served as a hosted/multi-tenant
endpoint. Tracked now so "production-grade" (the 0.1 bar) doesn't silently ship a
wide-open HTTP surface.

## Current behavior

- `MCPServer.from_http(host, port)` runs a Starlette app under uvicorn, mounted at
  `/mcp`, **stateless, no auth** (`serve/server.py` → framework
  `agentforge-mcp`). Defaults bind `127.0.0.1`.
- Mitigation today (documented in `docs/guides/10-using-over-mcp.md`): bind
  localhost; for remote, front it with a reverse proxy doing TLS + authN. There is
  no in-process control.

## Proposed change

Layered, smallest-useful-first:

1. **Bearer-token gate** (MVP): an optional shared secret
   (`serve.http_auth_token` / `CKG_HTTP_AUTH_TOKEN`); reject requests without a
   matching `Authorization: Bearer …`. Off by default (preserves the localhost
   path); a one-line opt-in for any exposed port.
2. **Bind-safety**: warn (or refuse without `--allow-unauthenticated`) when
   `--transport http` binds a non-loopback host (`0.0.0.0`) with no token set.
3. **(Later) richer authZ**: per-token tool/scoping, or delegate to the framework
   if `agentforge-mcp` grows an auth hook (prefer reusing framework rails —
   file a `docs/framework/` wishlist note).

Decide whether token-checking belongs in our `serve` layer (a Starlette
middleware we add) or upstream in `agentforge-mcp`. If upstream can host it, we
configure rather than implement (mirrors the provider/storage-registry stance).

## Acceptance criteria

- HTTP transport can require a bearer token from config/env; unauthenticated
  requests get `401`, and the token never appears in logs.
- Binding a non-loopback host without auth is a loud, deliberate opt-in, not a
  silent default.
- stdio transport is unchanged (no auth needed — the client owns the subprocess).
- Guide updated; an env-gated test exercises the authed path.

## Resolution (2026-06-15)

Shipped the bearer-token gate + bind-safety (layers 1–2):

- **Bearer gate** — `serve.http_auth_token` / `$CKG_HTTP_AUTH_TOKEN`. When set,
  every HTTP request must carry a matching `Authorization: Bearer …` (constant-time
  compare); others get `401` with a `WWW-Authenticate: Bearer` header. The token is
  never logged. **Off by default** — the localhost loop is unchanged.
- **Bind-safety** — `build_mcp_server` *refuses* a non-loopback bind (`0.0.0.0`)
  with no token unless `--allow-unauthenticated` (a loud, deliberate opt-in). The
  check runs **before** the engine opens, so a misconfig fails fast.
- **stdio** is untouched (no auth — the client owns the subprocess).

**Implementation (simplified in 0.4.0):** `agentforge-mcp` ≥0.3 exposes a
`from_http(middleware=…)` seam, so the authed path passes a pure-ASGI
`BearerAuthMiddleware` (`serve/http_runner.py`) as a Starlette `Middleware` and
lets the framework build/serve the app — no runner reimplementation. The no-auth
path stays 100% framework. CLI: `--auth-token` / `--allow-unauthenticated`.
*(Originally we injected a custom `CkgHttpRunner` because 0.2.4 had no auth hook;
dropped once the framework added `middleware=` — see
`docs/framework/upgrade-0.2.4-to-0.3.x.md`.)*

**Verified:** always-on unit tests cover the middleware (401 missing/wrong, 200
correct, lifespan pass-through) + the bind-safety guard; a live HTTP test
(`CKG_LIVE_MCP_HTTP=1`) starts a real uvicorn server and confirms 401 for
unauthenticated and pass-through for the right token. 463 passed, 93% cov. Layer 3
(per-token scoping) deferred — file as a follow-up if a deployment needs it.

## Notes / alternatives

- "Just use a proxy" is the 0.1 answer and stays valid — this ENH makes the
  **simple** secure deployment not *require* extra infrastructure.
- Keep it off by default so the localhost dev loop (the common case) needs no
  token. See [feat-008](../features/feat-008-mcp-server-and-tool-api.md) and the
  consumption guide [`using-over-mcp.md`](../guides/10-using-over-mcp.md).
