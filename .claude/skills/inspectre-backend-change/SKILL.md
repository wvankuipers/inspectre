---
name: inspectre-backend-change
description: Use for any backend (Django/DRF) feature or bugfix in this repo's `core` app — models, serializers, views, Celery image pipeline, or settings.
---

# Inspectre backend change

Chains the standard Superpowers workflow with this repo's specific gates. Follow in order:

1. **Design** — **REQUIRED SUB-SKILL:** `superpowers:brainstorming` for a new feature, or
   `superpowers:systematic-debugging` for a bug (write a failing test that reproduces it
   before touching implementation code).
2. **Plan tests** — **REQUIRED SUB-SKILL:** `superpowers:test-driven-development` to
   define the test(s) before writing implementation.
3. **Implement** — **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`.
   Never implement directly in the main session. That skill expects a written plan/task
   brief before it dispatches — for a small fix with no separate plan doc, write a
   minimal task brief (what's broken, the failing test, the fix scope) first rather than
   skipping straight to dispatch.
4. **Test** — run `make test-fast` (serializers, SPA API, admin, models, health,
   settings, Celery fencing — no ImageMagick, ~1s). If the change touches image
   diffing/comparison, baseline upsert, seed, or the legacy API, also run
   `make test-slow` (~5s, real `convert`/`compare`).
5. **Lint** — run `make lint-fix` (ruff: E, F, I, B, UP, DJ; line length 120). No task is
   done with outstanding lint violations.
6. **Docs** — if this change altered models, API surface (`/api/*` or legacy), the image
   pipeline, storage layout, or settings, **REQUIRED SUB-SKILL:** `inspectre-sync-docs`
   before finishing.
7. **Finish** — **REQUIRED SUB-SKILL:** `superpowers:finishing-a-development-branch`.
   Never commit or push directly to `main` — feature branch + PR only, and
   `make test`/`make lint` must pass first.
