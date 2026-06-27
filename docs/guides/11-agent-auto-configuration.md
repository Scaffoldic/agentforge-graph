# Wiring the CKG into your agent (`ckg setup`)

> **TL;DR:** `ckg setup` writes your coding agent's MCP config for you — a
> repo-root `.mcp.json` by default (`--scope user` for the global config) — and
> `--hooks` adds a short nudge to `AGENTS.md`/`CLAUDE.md` so the agent reaches
> for the `ckg_*` tools instead of grepping. Every write shows a diff first, is
> marked as ours, and is reversible with `--undo`.

Guide [10](10-using-over-mcp.md) shows the *manual* MCP wiring; this guide is the
one-command path that does it for you (feat-013).

---

## 1. Try it with zero install

`ckg` is a console entry point, so you can run it without installing anything —
`uvx` (uv) or `pipx run` each spin up a throwaway environment:

```bash
uvx agentforge-graph index .                 # build the graph, no venv
uvx agentforge-graph serve-mcp --repo .       # serve it over MCP
# or: pipx run agentforge-graph index .
```

`ckg --version` reports how it was launched, e.g. `ckg 0.7.0 (uvx)` — handy in a
bug report. When you're ready to keep it, `uv pip install agentforge-graph` (or
`pipx install`) puts `ckg` on PATH.

## 2. Wire your agent

From inside the repo you want the agent to know:

```bash
ckg setup
```

It detects your agent, shows a plan/diff, and asks before writing:

```
Detected agents:
  ✓ Claude Code        reads ./.mcp.json     (will add MCP server "ckg")
Plan (scope: project, transport: stdio):
  + ./.mcp.json  [create]  (Project .mcp.json (MCP standard))

Apply? [y/N]
```

After writing, it spawns the server once and confirms it answers (`connected ✓`).

```bash
ckg setup --print     # dry-run: show the plan, write nothing
ckg setup --hooks     # also add the "prefer the graph" nudge to AGENTS.md/CLAUDE.md
ckg setup --yes       # apply without the prompt (scripts/CI)
ckg setup --undo      # remove everything ckg setup added
```

## 3. Project vs user scope — which to use

| | `--scope project` (default) | `--scope user` |
|---|---|---|
| Writes | `<repo>/.mcp.json` | `~/.claude.json` (the agent's global config) |
| Applies to | this repo | you, on this machine, across projects |
| Shareable | ✅ **commit it** → the whole team's agents are wired | ❌ each person runs setup |
| Path written | relative (`--repo .`, portable) | absolute repo path |
| Touches | a new file in the repo | your personal global config |

The graph is per-repo, so **project scope is the default** — and committing
`.mcp.json` means a teammate who clones the repo is wired automatically. Use
`--scope user` for a solo "wire it on my machine" setup.

## 4. The nudge hooks (`--hooks`)

`--hooks` appends a managed block to `AGENTS.md` (and `CLAUDE.md` if present):

```markdown
<!-- agentforge-graph:start -->
## Prefer the code graph
For structural questions (callers, impact, routes, where-defined), use the
ckg_* MCP tools instead of grep/glob — cheaper and grounded. Fall back to file
reads only when the graph can't answer.
<!-- agentforge-graph:end -->
```

It's **non-blocking** — context only, never overriding the agent's tool choices —
and idempotent (re-running replaces the block, never duplicates it).

## 5. Configure defaults (optional)

Set defaults in `agentforge.yaml` (under `app:`) or a standalone `ckg.yaml`:

```yaml
setup:
  scope: project          # project (default) | user
  transport: stdio        # stdio (default) | http
  install_hooks: false    # true → install the nudge block by default
  agents: []              # [] = auto-detect; else an allowlist of adapter keys
```

CLI flags always override config.

---

## Operational reference

What `ckg setup` writes, and the guarantees that make it safe to run on a repo
you didn't author the config for.

### What gets written

| Scope / flag | File | Change |
|---|---|---|
| `--scope project` (default) | `<repo>/.mcp.json` | adds `mcpServers.ckg` = `ckg serve-mcp --repo .` |
| `--scope user` | `~/.claude.json` | adds `mcpServers.ckg` pointing at the absolute repo path |
| `--transport http` | (same file) | writes a `url` entry; **refuses** a non-loopback host with no token (ENH-005) |
| `--hooks` | `AGENTS.md` / `CLAUDE.md` | appends the marked nudge block |

### Safety guarantees

- **Structural, never textual.** Configs are parsed → our key set → re-serialized.
  Your other MCP servers and keys are preserved.
- **Marker-scoped.** Our MCP entry carries `"_managed_by": "agentforge-graph"`;
  the nudge block is fenced by `agentforge-graph:start/end` markers. We only ever
  replace or remove something carrying our marker.
- **Conflict-safe.** A `ckg` server *you* authored (no marker) is **never**
  overwritten — `ckg setup` reports a conflict and stops unless you pass
  `--force`.
- **Dry-run first.** Bare `ckg setup` shows the diff and asks; `--print` writes
  nothing; `--yes` is the explicit opt-out for automation.
- **Reversible.** `ckg setup --undo` removes exactly what we added (the MCP entry
  *and* the nudge block), and deletes a file that existed only to hold our entry.

### Re-running and upgrades

`ckg setup` is idempotent — running it again is a `noop` if nothing changed, or a
clean in-place `update` if the served repo/transport changed. After a CKG
version bump, re-run it to refresh the managed block.

### Troubleshooting

- **"agent not detected"** — the adapter probes conservatively (a real config dir
  or the agent's binary on PATH). Project scope still writes the portable
  `.mcp.json` regardless, which any MCP-aware agent reads.
- **"connection check: warning"** — the config was written, but the spawned
  server didn't answer. Make sure the repo is indexed (`ckg index .`) and try
  `ckg serve-mcp --repo .` manually. Skip the check with `--no-check`.
- **conflict on `ckg`** — you already have a `ckg` MCP server you wrote; remove it
  or re-run with `--force` to replace it with the managed entry.
