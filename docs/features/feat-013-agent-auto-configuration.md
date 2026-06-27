# feat-013: Agent auto-configuration & frictionless first run

## Metadata

| Field | Value |
|---|---|
| **ID** | feat-013 |
| **Title** | Agent auto-configuration & frictionless first run |
| **Status** | accepted (graduated from FA-002 + FA-001 Phase 1) |
| **Owner** | kjoshi |
| **Created** | 2026-06-27 |
| **Target version** | 0.7.0 |
| **Languages** | n/a (operates on agent tooling, not indexed source) |
| **Module package(s)** | `agentforge_graph.setup` (framework layer) + onboarding docs |
| **Depends on** | feat-008 (MCP server + `ckg serve-mcp`), ENH-003 (registry pattern) |
| **Blocks** | none (adoption layer; nothing depends on it) |
| **Graduated from** | `docs/feature-analysis/FA-002` (full) + `FA-001` Phase 1 |

---

## 1. Why this feature

The engine is strong and now public, but two onboarding gaps stand between
"installed" and "an agent is querying my repo":

1. **Wiring is manual.** After `pip install`, the user must hand-edit their
   coding agent's config to add an MCP server entry — find the file, write a
   valid entry, get `command`/`args` right, point it at the repo. This is the
   documented path in `docs/guides/10-using-over-mcp.md`
   (`claude mcp add ckg -- ckg serve-mcp --repo .`), but it is per-agent and
   error-prone.
2. **Even when wired, agents don't reach for the graph.** Left to defaults an
   agent greps and reads files — exactly the token-heavy exploration the CKG
   exists to replace — because nothing tells it the graph is available or
   cheaper.

This feature closes both: a `ckg setup` command that **auto-detects installed
agents and writes their MCP config**, plus **optional, non-blocking nudge
hooks** that steer an agent from raw file exploration toward the graph tools.
It also blesses the **zero-install trial path** (`uvx` / `pipx run`) so the
"try it in one command" story needs no venv (FA-001 Phase 1).

## 2. Why it must ship in the agent core

- **The wiring is part of the contract.** The MCP entry's command, args, and
  transport are owned by us (feat-008); a generator that emits them correctly
  removes a whole class of "it didn't connect" support load.
- **Discoverability is a feature.** A connected-but-unused graph delivers no
  value. Steering agents toward it is the difference between "installed" and
  "actually saving tokens."
- **One generator, many targets.** Encoding each agent's config shape once,
  centrally, beats every user re-deriving it from the guide — and mirrors how
  storage backends (ADR-0006) and providers (ENH-003) already register
  out-of-core.

## 3. How consumers benefit

- **New user:** `ckg setup` detects Claude Code, writes the MCP entry pointing
  at the current repo, confirms the connection — no hand-editing JSON. And
  before installing anything, `uvx agentforge-graph index .` gives a no-venv
  trial.
- **Existing user:** `ckg setup --print` shows exactly what *would* be written
  (no surprises); `ckg setup --agent claude-code` targets one.
- **Agent at runtime:** with `--hooks` installed, the agent is reminded that
  `ckg_search` / `ckg_repo_map` / `ckg_impact` exist and are cheaper than
  grepping — so it uses them.

## 4. Feature specifications

### 4.1 User-facing experience

**Zero-install trial (FA-001 Phase 1 — no PATH change, no venv):**

```bash
uvx agentforge-graph index .                    # uv-managed throwaway env
pipx run agentforge-graph serve-mcp --repo .     # same, via pipx
```

**Auto-configuration:**

```bash
ckg setup                       # detect agents, show the plan/diff, apply on confirm
ckg setup --print               # dry-run: print the plan, write nothing
ckg setup --scope project       # write repo-root .mcp.json (DEFAULT; shareable)
ckg setup --scope user          # write the user-global agent config instead (~/.claude.json)
ckg setup --agent claude-code   # target a specific agent
ckg setup --repo .              # repo the MCP entry should serve (default: cwd)
ckg setup --hooks               # also install the optional nudge hooks
ckg setup --yes                 # skip the confirm prompt (scripts / CI)
ckg setup --no-check            # skip the post-write connection check
ckg setup --undo                # remove entries/hooks this tool added
```

Default flow (interactive, **shows the diff before writing**):

```
$ ckg setup
Detected agents:
  ✓ Claude Code        reads ./.mcp.json              (will add MCP server "ckg")
  – <agent B>          not installed                  (skipped)

Plan (scope: project):
  + ./.mcp.json → MCP server "ckg" = ckg serve-mcp --repo .  (stdio)

Apply? [y/N]
```

### 4.2 Public API / contract

- **New subcommand `ckg setup`** with the flags above. **Idempotent:** running
  twice does not duplicate entries; it reconciles to the desired state.
- **Scope (resolved):** `--scope project` (**default**) writes a **repo-root
  `.mcp.json`** — the portable, shareable MCP standard (Claude Code and other
  `.mcp.json`-aware clients read it; commit it and the whole team's agents are
  wired). `--scope user` writes the **user-global** agent config
  (`~/.claude.json`) for the solo "wire it on my machine" case. The CKG's
  knowledge is inherently per-repo, so project scope is the natural default and
  has the smallest blast radius (a new repo file, never the user's global
  config). The served path is **relative** (`--repo .`) so a committed
  `.mcp.json` is portable across machines.
- **Consent (resolved — stateless):** the default flow **always shows the diff
  and asks** before writing; `--yes` skips the prompt for scripts/CI. No
  remembered-consent state is persisted (simpler, one fewer place to get
  wrong); `--print` writes nothing.
- **Detection registry** — a per-agent adapter describing: detection probe
  (does the config/dir exist), config path(s), config format
  (JSON/JSONC/TOML/YAML), the MCP-entry shape, and where hints live. New agents
  are added by registering an adapter, not by changing core logic (mirrors the
  ENH-003 provider registry / ADR-0006 storage registry).
- **Managed markers** — every block this tool writes is wrapped with a managed
  marker (e.g. a JSON key `"_managed_by": "agentforge-graph"`) so `--undo`
  removes exactly what we added and nothing the user authored.
- **`ckg --version` channel awareness** (FA-001 Phase 1) — report how `ckg` was
  invoked (`pip` / `uvx` / `pipx`) so support can tell install method from a
  bug report. (Homebrew/standalone channels are FA-001 Phase 2+, out of scope.)

### 4.3 Internal mechanics

- **MCP entry generation.** For each detected agent, render the **stdio**
  transport entry by default
  (`command: "ckg", args: ["serve-mcp", "--repo", "<repo>"]`) — stdio needs no
  port/auth and the client owns the subprocess lifetime (feat-008 stdio-default
  + ENH-005 "stdio needs no auth"). HTTP wiring is opt-in (`--transport http`),
  and when chosen the generator **refuses a non-loopback target without a
  token** (carries ENH-005's bind-safety into the generated config).
- **Format-aware editing.** Edit JSON/JSONC/TOML/YAML **structurally**
  (parse → merge our key → serialize), never by string-splicing, so the user's
  existing servers and comments survive.
- **Connection check.** After writing, optionally spawn the configured server
  once and confirm it answers a `ckg_status` call, reporting success/failure.
- **Nudge hints (optional, `--hooks` — chunk 2, resolved).** Append a short
  **managed block** to the repo's agent-instructions file
  (`AGENTS.md`/`CLAUDE.md`) telling the agent to prefer the `ckg_*` tools over
  grep/glob for structural questions. This is **repo-level** (matches the
  `.mcp.json` default), **portable** (every `AGENTS.md`-aware agent reads it),
  and inherently **non-blocking** — it adds context, never overrides the
  agent's tool choices. The block is wrapped in
  `<!-- agentforge-graph:start -->` / `<!-- agentforge-graph:end -->` markers so
  `--undo` removes exactly it and nothing the user wrote. (An active
  Claude-Code `PreToolUse` hook was considered and rejected for v1: Claude-only
  and noisy on every search.)

### 4.4 Module packaging

New `agentforge_graph.setup` — the ADR-0001 **framework layer** (it is a
consumer-facing convenience; it may import the framework). The deterministic
engine (`core`/`ingest`/`store`/`retrieve`) stays untouched. `ckg setup`
console-script entry. FA-001 Phase 1 adds **no importable code** — it is docs +
a `--version` channel stamp.

### 4.5 Configuration

```yaml
setup:
  scope: project            # project (default; repo .mcp.json) | user (~/.claude.json)
  transport: stdio          # stdio (default) | http
  install_hooks: false      # opt-in nudge hooks (AGENTS.md/CLAUDE.md managed block)
  agents: []                # empty = auto-detect all; or an allowlist
```

## 5. Plug-and-play & upgrade story

- Adding support for a new agent = registering one adapter; no core change.
  Unknown/unsupported agents are listed as "skipped," never guessed at.
- Managed markers make the operation reversible and re-runnable; a CKG version
  bump can rewrite its own managed block without disturbing the user's edits.

## 6. Cross-language parity

n/a — operates on agent tooling, independent of indexed-language coverage.

## 7. Test strategy

- **Per-adapter golden tests:** given a fixture config (empty, and one with
  pre-existing servers), assert the post-`setup` config exactly matches a
  golden file — proves we merge, not clobber, and preserve formatting.
- **Idempotency test:** running `setup` twice yields a byte-identical config
  the second time (no duplicate entries).
- **Undo test:** `setup` then `setup --undo` returns the config to its original
  bytes.
- **Format-preservation test:** JSONC/TOML comments and unrelated keys survive
  a round-trip.
- **Bind-safety test:** `--transport http` targeting a non-loopback host with
  no token refuses to write (carries ENH-005's guard).
- **Connection check (env-gated):** the generated stdio entry launches and
  answers `ckg_status`.
- **Hooks test (chunk 2):** a `--hooks` install writes a non-blocking hint,
  `--undo` removes it, and the hint never blocks the agent's own tools.
- **Trial-path smoke (FA-001 P1):** `uvx`/`pipx run` of the published package
  runs `ckg index` + `ckg serve-mcp` end-to-end (CI, creds-free).

## 8. Risks & open questions

| Risk / Question | Mitigation / Decision |
|---|---|
| Corrupting a user's hand-edited agent config | Structural parse/merge only; managed markers; `--print` dry-run + confirm on first run; `--undo` |
| Agent config formats drift over time | Adapters are versioned and golden-tested; a broken adapter fails its test, not silently mis-writes |
| Hooks perceived as intrusive / noisy | Off by default (`--hooks` opt-in); strictly non-blocking; short, rate-limited hints |
| Over-broad detection (claiming an agent that isn't there) | Conservative probes (require the real config dir/binary); ambiguous → "skipped," reported, never written |
| Which agents to support first | **Claude Code first** (we dogfood it); the registry makes additions cheap (one file + goldens) |

## 9. Out of scope

- **FA-001 Phases 2–3** — Homebrew tap, `install.sh`/`install.ps1`, multi-OS
  self-contained bundle, `ckg self-update`. Heavy ops + ongoing maintenance;
  revisit once `uvx`/`pipx` demand is proven. (FA-001 Phase 1 only — blessing
  `uvx`/`pipx run` — is in scope here.)
- **FA-004 local embeddings** — separate sequenced follow-on (`[local-embed]`
  extra).
- Installing the agents themselves (we configure what's present).
- Writing **blocking** policy hooks that override an agent's tool choices —
  hints only.
- A GUI configurator.

## 10. Design notes

**Two chunks, sequenced.** Chunk 1 = the config generator (high value, low
risk: detection registry + Claude Code adapter + structural editing + dry-run +
`--undo` + connection check) **plus** FA-001 Phase 1 (bless `uvx`/`pipx`,
`--version` channel stamp, getting-started doc). Chunk 2 = the nudge hooks
behind `--hooks` (Claude Code first). Both land under feat-013.

**Safety is the headline.** Because we edit files the user did not create, the
non-negotiables are: structural (not textual) edits, managed markers, dry-run
visibility, and reversible `--undo`. A config generator that occasionally
corrupts a user's setup is worse than no generator. Hence bare `ckg setup`
**always shows the diff and confirms before writing** (stateless — no
remembered-consent file); `--yes` skips the prompt for scripts/CI and `--print`
writes nothing.

**Resolved decisions (this feat).** (1) **Default scope = repo-level
`.mcp.json`**, `--scope user` for the global config — the graph is per-repo, so
project scope matches it 1:1, is shareable/committable, and only ever adds a
file inside the repo. (2) **Stateless confirm** (always ask unless `--yes`).
(3) **Nudge = a managed block appended to `AGENTS.md`/`CLAUDE.md`** (portable,
non-blocking), not an active Claude-only hook. (4) **Docs are a deliverable** —
see §12.

**Registry-first, like the rest of the system.** Agent adapters mirror the
storage (ADR-0006) and provider (ENH-003) registries. The core `setup` flow is
agent-agnostic; each agent is data + a small adapter with its own goldens, so a
new agent's blast radius is one file.

**Why FA-001 Phase 1 rides along.** `ckg` is already a console entry point, so
blessing `uvx`/`pipx run` is near-zero code — mostly a getting-started doc and
a `--version` channel stamp. It completes the "install (or don't) → wire →
used" onboarding spine in one feat, while the heavy distribution work
(Phases 2–3) is deferred until demand justifies the build-matrix maintenance.

## 11. References

- `docs/feature-analysis/FA-002` (agent auto-configuration — full source) and
  `FA-001` (frictionless install — Phase 1 only graduated here).
- feat-008 (MCP server + `ckg serve-mcp` — the entry this wires), ENH-005
  (HTTP bind-safety carried into generated configs).
- ENH-003 provider registry / ADR-0006 storage registry — the registry pattern
  the agent-adapter registry mirrors.
- `docs/guides/10-using-over-mcp.md` — the manual steps `ckg setup` automates.

## 12. Documentation deliverables

Docs ship **with** the feature (part of the definition of done), not after:

- **Guide — `docs/guides/NN-getting-started-and-setup.md`** (consumer how-to):
  the zero-install trial (`uvx`/`pipx run`), `ckg setup` walkthrough,
  **project vs `--scope user`** (when to commit `.mcp.json` vs wire it
  globally), `--print`/`--hooks`/`--undo`, the AGENTS.md nudge block, and
  troubleshooting (agent not detected, connection check failed). Slots into the
  existing NN-slug guide series and is linked from the README quickstart.
- **Runbook — `docs/runbooks/agent-setup.md`** (operational): exactly what
  `ckg setup` writes for each scope, the managed-marker format, how `--undo`
  reverses it, how to re-run after a CKG upgrade, and the safety guarantees
  (structural edits, dry-run, reversible). The reference an operator reads
  before running it on a shared repo.
- **README + `10-using-over-mcp.md` cross-links** — point the manual MCP-wiring
  steps at `ckg setup` as the one-command path, keeping the manual steps as the
  "what it does under the hood" reference.

A docs-presence check is part of the feature's test strategy (§7): the guide
and runbook exist and the README quickstart links the new path.
