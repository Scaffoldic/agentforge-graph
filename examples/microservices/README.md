# Microservices demo — org-level central knowledge end-to-end

Four services that call each other; one federated MCP endpoint over the whole
org. This exercises the **0.5 org-central-knowledge** features end-to-end:
ENH-019 (cwd discovery), ENH-018 (central hosting + read-only), ENH-020
(federation + cross-service tracing).

```
web ──fetch──▶ gateway ──httpx(base_url)──▶ orders ──requests──▶ payments
 (JS)          (FastAPI)                     (FastAPI)            (OpenAPI only)
```

- **web** (JS) calls the gateway with `fetch`.
- **gateway** (FastAPI) proxies to orders via an `httpx.Client(base_url=…)` instance.
- **orders** (FastAPI) charges via `requests.post(".../v1/charge")`.
- **payments** is **contract-first** — just an `openapi.yaml`, no framework code.

## 1. Index every service into a central store (ENH-018)

Host the indexes centrally instead of in each repo. Point a config at a shared
root (here per service; in a real org, CI builds these):

```bash
# from examples/microservices/
for s in web gateway orders payments; do
  printf 'store:\n  central_root: ~/.agentforge/ckg-demo\n' > "$s/ckg.yaml"
  ckg index "$s"
done
ckg status orders          # → store: …/ckg-demo/<repo-key>  (central)
```

The `.ckg/` artifacts live under `~/.agentforge/ckg-demo/<repo-key>`, **not** in
the repos — one collision-free subdir per service.

## 2. Consume read-only (ENH-018)

A developer/agent consumes the central index without being able to mutate it:

```bash
ckg index orders --read-only      # → refuses (exit 2): consume-only
ckg routes orders --read-only     # → works (read)
```

## 3. Serve the repo you're in, no --repo (ENH-019)

```bash
cd orders/src 2>/dev/null; cd ..    # anywhere inside a service
ckg serve-mcp                       # discovers the service from the cwd
```

## 4. Federate the whole org + trace requests (ENH-020)

```bash
ckg serve-mcp --workspace workspace.yaml
```

One endpoint. In an MCP client, the cross-service tools answer:

- **`ckg_services_map`** → the org call graph:
  `web → gateway` (fetch), `gateway → orders` (httpx+base_url),
  `orders → payments` (requests, matched to payments' OpenAPI `chargeCard`,
  `via: openapi`).
- **`ckg_trace` `{ "service": "web" }`** → downstream data flow:
  reaches `gateway, orders, payments`.
- **`ckg_trace` `{ "service": "payments", "direction": "upstream" }`** → blast
  radius: `orders, gateway, web` — *"who breaks if I change the charge contract."*

> The cross-service edges are computed live at federation time (member graphs are
> separate stores). Survey tools (`ckg_search`/`ckg_routes`/…) also fan across all
> four services and tag results by `service`.
