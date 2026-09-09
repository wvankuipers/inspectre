---
name: inspectre-architecture-review
description: Use when auditing the running Inspectre app as a whole for UX, accessibility (ARIA), performance, or architecture-consistency issues, rather than reviewing one specific diff.
---

# Inspectre architecture review

Unlike `inspectre-backend-review`/`inspectre-frontend-review` (scoped to one diff), this
is a whole-app audit run against the live SPA + API + `docs/`. Ground every finding in
this repo's actual conventions and code — not generic heuristics — and confirm each one
live before reporting it.

## Setup

Ensure the stack is current (`make up`; rebuild anything stale), then walk the app via
Chrome DevTools MCP or Playwright MCP starting at `http://localhost:4200`.

## Dimensions

**UX** — Walk the golden path: projects list → project/suite detail → run detail → image
viewer → set baseline → cross-run history (`TestDetailComponent`). Check: empty/error
states match the `ErrorInterceptor`/snackbar contract; filter+sort+search behave
consistently across `ProjectsListComponent`/`SuiteDetailComponent`/`RunDetailComponent`;
non-obvious affordances (compare-mode **vs** toggle, divider drag, "Set as baseline")
are actually discoverable; deviations from `docs/ui.md`'s visual-token/chip conventions.

**ARIA / accessibility** — **REQUIRED SUB-SKILL:** `chrome-devtools-mcp:a11y-debugging`
for audit method. Focus specifically on: `ImageViewerComponent`'s modal focus trap and
focus-return on close; whether the compare-mode divider (mouse/touch drag only, per
`docs/ui.md`) has a keyboard-operable equivalent; status chips (`chip-pass`/`chip-fail`/
`chip-new`) conveying meaning by color alone without text/icon redundancy; contrast
ratios for the design tokens in `docs/ui.md`; missing `alt` text on
screenshot/baseline/diff images and thumbnails.

**Performance** — **REQUIRED SUB-SKILL:** `chrome-devtools-mcp:debug-optimize-lcp` for
LCP work; use `performance_start_trace`/`performance_stop_trace` and `lighthouse_audit`.
Focus on: thumbnail lazy-loading correctness and thumbnail-vs-displayed-size mismatches
on `RunDetailComponent`'s image grid; `POST /api/tests/bulk/` polling frequency/payload
size; any N+1 pattern (per-row calls where a bulk endpoint exists); confirming the
zoneless build shipped with no `zone.js` in the bundle.

**Architecture consistency** — Cross-check `docs/decisions.md`'s config-knobs table and
known functional gaps against current `settings.py`/code for drift. Confirm the legacy
(frozen, un-prefixed) and SPA (`/api/*`) endpoint surfaces haven't been accidentally
coupled — a legacy-endpoint change is a breaking change, an SPA one isn't. Confirm
`frontend/src/app/core/models/api.ts` still mirrors the DRF serializers field-for-field
app-wide, not just in the last diff. Spot-check the `Test`/`Baseline` model invariants
and Celery fencing/retry logic (see `inspectre-backend-review`'s checklist) for drift
anywhere in the codebase, not only recently changed files.

## Reporting

Report via the `ReportFindings` tool, grouped by dimension, most severe first. A finding
must be reproduced live (in the browser, in the code, or both) before it's reported —
don't report a suspicion as a finding.
