# ENH-016: hosted documentation site

| Field | Value |
|---|---|
| **ID** | ENH-016 |
| **Value/Impact** | Med (discoverability + polish for the public launch) |
| **Effort** | S–M |
| **Status** | proposed (post-public candidate) |
| **Area** | docs / infra |
| **Relates to** | the OSS-readiness work (README, guides, examples) |

## Motivation

The docs are markdown in-repo (README, `docs/guides/`, ARCHITECTURE, ADRs, feature
specs). They're complete but only browsable on GitHub. A **hosted, searchable
docs site** gives the project a polished front door for the public launch — a
landing page, the quick start, the feature guides, and an auto-generated API
reference, all searchable with a clean URL.

## Analysis — approach

- **MkDocs + Material** (Python-native, matches the project) with:
  - The existing `docs/guides/*` as the nav (almost zero rewriting).
  - **`mkdocstrings`** to auto-generate an API reference from the package
    docstrings — the public surfaces (`CodeGraph`, the CLI, the MCP tools,
    `core.contracts`) are already well-documented.
  - A short landing page derived from the README's "out of the box" section.
- **Deploy:** GitHub Pages via an Actions workflow (`mkdocs gh-deploy` on tag /
  on push to main). A `docs` extra holds `mkdocs-material` + `mkdocstrings`.
- The repo's `[project.urls].Documentation` repoints from the GitHub blob URL to
  the site.

## Risks

| Risk | Mitigation |
|---|---|
| Free GitHub Pages needs the repo **public** | Gate this on the repo going public (it's the front door for exactly that moment) |
| Doc drift between site and code | `mkdocstrings` pulls API docs from source; guides stay in-repo and are the same files |
| Maintenance | CI builds the site on every push; a broken-link check in the docs workflow |

## 0.4.0 candidacy

**Post-public**, not a 0.4.0 blocker — it's the launch front door, most valuable
the moment the repo goes public. Low effort given the guides already exist; can
land in the same window as flipping the repo public.
