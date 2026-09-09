# Inspectre — Claude Code Instructions

Visual regression testing SaaS: CI pipelines upload screenshots via the REST API; the
backend (Django/DRF) diffs them against baselines; the Angular SPA lets users review
and promote results. Full architecture reference: `docs/README.md` and its linked docs
(models, API, image pipeline, storage, routes, infra, deployment).

## Required Workflow

1. Invoke the relevant `superpowers:*` skill before starting any task
   (`brainstorming` for features, `systematic-debugging` for bugs), and implement via
   `superpowers:subagent-driven-development` — never directly in the main session.
2. Test-first for bug fixes (failing test before the fix); all changes need test
   coverage. Never mark a task done with failing tests.
3. After rebuilding the SPA container, verify in browser with Chrome DevTools MCP
   (`http://localhost:4200`, screenshot) before reporting a frontend task complete.
4. Never load assets (fonts, icons) from a CDN — self-host/inline them.
5. `make test` and `make lint` must pass, and `make lint-fix` must be run, before
   finishing a branch or opening a PR.
6. Never commit or push directly to `main` — always a feature branch + PR.
7. Update `docs/` (and this file, if workflow rules change) in the same task whenever
   architecture, API surface, routes, or models change.
