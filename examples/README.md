# Examples

Runnable sample repos to index with agentforge-graph and see the differentiators
in one minute.

## `fastapi-shop/` — routes, ORM models, DI in one file

A tiny FastAPI + SQLAlchemy app (two endpoints, two models with a relationship +
foreign key, one injected dependency). Index it and explore the **framework
graph** — no cloud, no server:

```bash
pip install agentforge-graph

ckg index examples/fastapi-shop

ckg routes
#   GET   /users/{uid}          →  get_user().      (app.py:42)
#   POST  /users/{uid}/orders   →  create_order().  (app.py:47)

ckg models
#   orders [orders]  (app.py:33)
#       fields: id, total_cents, user_id
#       relations: user→users (relationship), user_id→users (fk)
#   users [users]  (app.py:24)
#       fields: email, id, name
#       relations: orders→orders (relationship)

ckg services
#   get_db  (app.py:43)
#       injected into: create_order()., get_user().

ckg map --budget 1000        # centrality-ranked orientation
```

Add semantic search (needs an embedding provider — see
[`docs/guides/08-model-providers.md`](../docs/guides/08-model-providers.md)):

```bash
pip install 'agentforge-graph[bedrock]'      # or [openai], or a local server
ckg embed examples/fastapi-shop
ckg query "where are orders created" --path examples/fastapi-shop
```

## Serve it to an agent

```bash
ckg serve-mcp --repo examples/fastapi-shop   # 10 read-only MCP tools
```

→ More: the [feature guides](../docs/guides/) cover framework extraction,
decisions, temporal/history, enrichment, and retrieval in depth.
