---
name: inspectre-backend-review
description: Use to review backend (Django/DRF `core` app) changes in this repo — models, serializers, views, Celery image pipeline, settings, or migrations.
---

# Inspectre backend review

Review the diff against this repo's actual backend conventions (`docs/data-model.md`,
`docs/api.md`, `docs/image-diffing.md`, `docs/storage-and-thumbnails.md`,
`docs/admin.md`), not generic Django best practice. **REQUIRED SUB-SKILL:**
`superpowers:requesting-code-review` for the overall review flow; use this checklist as
the domain-specific lens.

## Checklist

- **API surface boundaries** — legacy endpoints (`/runs`, `/tests`, `/tests/<id>/status`,
  `/baselines/<key>.*`) are frozen; the Client API implementation calls these. A change
  to their request/response shape is a breaking change, not a free evolution. `/api/*`
  (SPA) endpoints can evolve freely.
- **Test model invariants** — `original_passed` must stay a tamper-proof snapshot of the
  initial pass/fail; don't let later code overwrite it. `Test.key` is derived from
  (project, suite, name, browser, size) — check any change touching key derivation
  against every place that already assumes uniqueness on that tuple.
- **Baseline FK** — `Baseline.test` is `SET_NULL` and informational only; don't add logic
  that depends on it staying populated.
- **Celery correctness machinery** — `process_test` relies on a Postgres advisory lock, a
  `processing_claim` fencing token, and `PROCESS_TEST_MAX_ATTEMPTS` with
  requeue-on-lock-contention. Any change to this task must not bypass the fencing token
  check or the retry cap — that's how concurrent/duplicate delivery correctness is
  maintained.
- **Staging cleanup** — uploads are staged to S3 (`screenshots/staging/{test_id}/upload.png`)
  and must be deleted after processing, on both success and failure paths.
- **First-upload path** — when no baseline exists yet, the code takes a distinct path
  (store only, no diff/compare) — verify this isn't accidentally merged with the
  diff-and-compare path.
- **Settings** — new tunables belong in the `Key settings` table pattern
  (`backend/inspectre/settings.py`) with a sane default; verify docs get updated
  (`docs/deployment-and-config.md` env var table or `docs/decisions.md` config knobs).
- **Auth** — both API surfaces are intentionally `AllowAny`; don't add auth-guarding
  to one surface without checking it's actually the right layer (Django admin already
  handles the one thing that needs auth).
- **Lint** — `ruff check` rules E, F, I, B, UP, DJ, line length 120. Flag violations even
  if `make lint-fix` would auto-fix them — the PR shouldn't ship with them uncommitted.
- **Test coverage** — every code change needs a test. If it touches ImageMagick
  compare/diff, baseline upsert, seed, or the legacy API, confirm a `make test-slow` test
  exists (fast pack has no real ImageMagick). If it touches Celery fencing/retry, confirm
  it's covered in the fast pack's Celery tests.

## Reporting

Verify each candidate finding against the actual diff before reporting — don't flag
generic style preferences. Report via the `ReportFindings` tool, most severe first.
