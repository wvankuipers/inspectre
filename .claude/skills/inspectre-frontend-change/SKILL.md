---
name: inspectre-frontend-change
description: Use for any Angular SPA feature or bugfix in this repo — routes, components, services, interceptors, or styles under `frontend/`.
---

# Inspectre frontend change

Chains the standard Superpowers workflow with this repo's specific gates. Follow in order:

1. **Design** — **REQUIRED SUB-SKILL:** `superpowers:brainstorming` for a new feature, or
   `superpowers:systematic-debugging` for a bug (write a failing test that reproduces it
   before touching implementation code).
2. **Plan tests** — **REQUIRED SUB-SKILL:** `superpowers:test-driven-development` to
   define the Vitest spec(s) before writing implementation.
3. **Implement** — **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`.
   Never implement directly in the main session. That skill expects a written plan/task
   brief before it dispatches — for a small fix with no separate plan doc, write a
   minimal task brief (what's broken, the failing test, the fix scope) first rather than
   skipping straight to dispatch. Reuse shared components under
   `frontend/src/app/core/components/` rather than adding new ad-hoc UI. Never load
   fonts/icons from a CDN — self-host/inline them.
4. **Test** — run `cd frontend && npm test` (Vitest + jsdom).
5. **Lint** — run `make lint-fix` (Angular ESLint + Prettier). No task is done with
   outstanding lint/formatting violations.
6. **Verify in browser** — **REQUIRED SUB-SKILL:** `inspectre-verify-spa-in-browser`.
   Never report a frontend task complete without this step. If the change needs a
   scripted multi-step interaction (drag, keyboard nav, filter+sort combos, reload
   persistence) rather than a single screenshot, use `inspectre-playwright-browser-test`
   instead/in addition.
7. **Docs** — if this change altered routes, components, services, or visual
   conventions, **REQUIRED SUB-SKILL:** `inspectre-sync-docs` before finishing.
8. **Finish** — **REQUIRED SUB-SKILL:** `superpowers:finishing-a-development-branch`.
   Never commit or push directly to `main` — feature branch + PR only, and
   `make test`/`make lint` must pass first.
