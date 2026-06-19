<!-- Thanks for contributing! Keep PRs to one feature/fix = one branch = one PR. -->

## What & why

What this changes and the motivation. Link the issue / feature spec / ADR if any
(e.g. `Closes #123`, `feat-0NN`, `ENH-0NN`).

## How

A short note on the approach — and, if it touches an extension point (a language
/ framework pack, storage backend, model provider, MCP tool, enricher), how it
rides the existing rails.

## Checklist

- [ ] `uv run ruff format --check . && uv run ruff check . && uv run mypy src` clean
- [ ] `uv run pytest` green (≥90% coverage)
- [ ] New behavior has tests (golden + end-to-end where it applies; new backends
      pass the conformance suite)
- [ ] Docs updated (README / a `docs/guides/` page / CHANGELOG `[Unreleased]`)
- [ ] No new `agentforge` import inside the deterministic engine (ADR-0001)
- [ ] Conventional-commit title (`feat:` / `fix:` / `docs:` / `chore:` / …)
