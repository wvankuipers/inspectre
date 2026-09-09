---
name: inspectre-frontend-review
description: Use to review Angular SPA changes in this repo — routes, components, services, interceptors, or styles under `frontend/`.
---

# Inspectre frontend review

Review the diff against this repo's actual frontend conventions (`docs/ui.md`), not
generic Angular best practice. **REQUIRED SUB-SKILL:** `superpowers:requesting-code-review`
for the overall review flow; use this checklist as the domain-specific lens.

## Checklist

- **Zoneless/standalone** — components must be standalone; no `NgModule`, no
  `zone.js`-dependent patterns (e.g. relying on implicit change detection instead of
  signals). `provideZonelessChangeDetection()` is load-bearing.
- **Component reuse** — check whether the change reinvents something already in
  `frontend/src/app/core/components/` (`app-shell`, `app-toolbar`, `breadcrumb`,
  `image-viewer`, `page-footer`, `run-stats-chips`, `search-field`). New ad-hoc UI for
  something one of these already does is a finding.
- **TypeScript models match serializers exactly** — `frontend/src/app/core/models/api.ts`
  mirrors DRF output field-for-field. A field rename/add on one side without the other
  breaks at runtime with no compile error (HTTP responses aren't type-checked). Also:
  `passed` (SPA `TestRow`) and `pass` (legacy) are intentionally separate — don't unify them.
- **Visual conventions** — background `#f1f5f9`, toolbar `#0f172a`, accent `#38bdf8`,
  `.inspectre-card` for cards, `.chip .chip-pass|chip-fail|chip-new|chip-none` for status
  pills. New one-off colors/spacing instead of these tokens is a finding. `chip-new-baseline`
  is intentionally scoped to `run-detail.component.scss`, not global — don't "fix" that
  by moving it to `styles.scss` without checking whether it's still only used there.
- **No CDN assets** — fonts/icons must be bundled/self-hosted (e.g. via Angular Material),
  never loaded from Google Fonts/CDN URLs.
- **Loading/error states** — `HttpClient` calls should go through `InspectreApiService`,
  not ad-hoc `HttpClient` injection, so `ErrorInterceptor`/`LoadingInterceptor` and the
  global loading indicator keep working. Image loading should reuse the `.img-skeleton`
  /`.img-loaded` shimmer pattern rather than a new one.
- **Sort/filter persistence** — table sort should go through `SortStateService`
  (`localStorage` key pattern `inspectre.sort.<table-id>`) if the component has a
  sortable table, consistent with `ProjectsListComponent`/`SuiteDetailComponent`/`RunDetailComponent`.
- **Routes** — new routes should nest under `AppShellComponent` and preserve the
  `** → /projects` catch-all; `/admin/*` must stay handled by nginx, not the Angular router.
- **Lint** — Angular ESLint + Prettier; flag violations even if `make lint-fix` would
  auto-fix them.
- **Test coverage** — Vitest + jsdom coverage for new/changed component logic, not just
  a passing build.

## Reporting

Verify each candidate finding against the actual diff before reporting — don't flag
generic style preferences. Report via the `ReportFindings` tool, most severe first.
