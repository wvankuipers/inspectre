# Web UI

The SPA is an **Angular** application served by nginx at port 4200 in the Docker stack. It talks exclusively to the Django REST backend via `HttpClient`. The legacy Rails ERB/jQuery frontend is no longer in use.

## Visual conventions

| Token | Value | Used for |
|-------|-------|----------|
| Background | `#f1f5f9` (slate-100) | Page background |
| Toolbar | `#0f172a` (slate-900) | Top navigation bar |
| Accent | `#38bdf8` (sky-400) | Links, active states, Angular Material cyan palette |
| Cards | `.inspectre-card` class | white, 10 px radius, subtle shadow |
| Status chips | `.chip .chip-pass` / `.chip-fail` / `.chip-new` / `.chip-none` | Test result pills |
| New baseline chip | `.chip-new-baseline` (component-scoped, `run-detail.component.scss`, not global) | Red/bold "New baseline" pill shown in `RunDetailComponent` when a test has no baseline yet |
| Font | Roboto (bundled via Angular Material, not loaded from CDN) | All text |
| Image skeleton | `#1e293b` with cyan shimmer sweep | Placeholder while images load |

Global styles live in `frontend/src/styles.scss`. Component-specific overrides live in each component's own `.scss` file.

## Routes

Routes mirror the legacy URL structure. Standalone components are lazy-loaded.

| Path | Component | Description |
|------|-----------|-------------|
| `/` | — | Redirect → `/projects` |
| `/projects` | `ProjectsListComponent` | Flattened table of projects + suites |
| `/projects/:projectSlug/suites/:suiteSlug` | `SuiteDetailComponent` | Latest 5 runs + all baselines |
| `/projects/:projectSlug/suites/:suiteSlug/runs/:seqId` | `RunDetailComponent` | Test table with thumbnails |
| `/projects/:projectSlug/suites/:suiteSlug/tests/:key` | `TestDetailComponent` | Cross-run pass/fail history for one test |
| `**` | — | Catch-all redirect → `/projects` |

The `/admin/*` path is never handled by the Angular router — nginx routes those requests directly to the Django API container before they reach the SPA.

## Feature components

### `ProjectsListComponent`

Route: `/projects`

Loads all projects via `GET /api/projects/`. Renders a flat table — one row per (project, suite) pair — with columns:

- **Project** — project name
- **Suite** — suite name, links to suite detail
- **Last run** — `#<seq_id>` with relative timestamp
- **Status** — pass/fail/new chips; only shown for statuses with count > 0. "No tests" pill if the latest run is empty.

The table is sortable by column (persisted to `localStorage` via `SortStateService`). A status filter dropdown (All / Pass / Fail / New) and a search field filter by project or suite name. Both filters apply simultaneously.

### `SuiteDetailComponent`

Route: `/projects/:projectSlug/suites/:suiteSlug`

Loads via `GET /api/projects/:proj/suites/:suite/`. Two sections:

**Latest runs tab** — table of up to 5 runs with run number, date, pass/fail/new chip counts. Rows link to run detail. The table is sortable.

**Baselines tab** — table of all current baselines for this suite (name, browser, size, thumbnail). Each thumbnail opens the image viewer modal. A search field filters by test name.

### `RunDetailComponent`

Route: `/projects/:projectSlug/suites/:suiteSlug/runs/:seqId`

Loads via `GET /api/projects/:proj/suites/:suite/runs/:seq/`. Renders a test table with columns:

- **Test** — name, browser, size; test name links to the test-detail route (`/projects/:proj/suites/:suite/tests/:key`); a "New baseline" chip (`.chip-new-baseline`) is shown when `!t.has_baseline`
- **Baseline** — 240×240 thumbnail
- **Comparison** — 240×240 thumbnail
- **Diff** — 240×240 thumbnail
- **Result** — `X% difference` + pass/fail/new chip + "Set as baseline" button

Thumbnails are lazy-loaded (`loading="lazy"`) with shimmer skeleton placeholders while loading. Clicking any thumbnail opens the `ImageViewerComponent` modal on that slot. Missing thumbnails show a `—` dash.

Filtering: a `SearchFieldComponent` filters by test name (debounced). A status chip filter (All / Pass / Fail / New) toggles inline. Both filters compose.

"Set as baseline" calls `POST /api/tests/:id/set-baseline/`. On success the chip flips from fail to pass optimistically and the button disappears.

### `TestDetailComponent`

Route: `/projects/:projectSlug/suites/:suiteSlug/tests/:key`

Loads via `GET /api/projects/:proj/suites/:suite/tests/:key/`, linked from the test name column in `RunDetailComponent`. Renders the cross-run pass/fail history for a single test as a table (columns: run, date, thumbnail, status), so a reviewer can see how one test has trended across runs without paging through each run individually.

## Core components

### `AppShellComponent`

Root layout. Contains `AppToolbarComponent` at the top, `<router-outlet>` for page content, and `PageFooterComponent` at the bottom.

### `AppToolbarComponent`

Top navigation bar (slate-900 background). Contains the Inspectre logo/wordmark on the left and the `BreadcrumbComponent` below it.

### `BreadcrumbComponent`

Dumb presentational component with a single `segments = input<BreadcrumbSegment[]>([])` input — it does not compute anything or resolve names itself. Callers (route components) build the `BreadcrumbSegment[]` array from the current route params and API response and pass it in. Renders the segments separated by `›`.

### `PageFooterComponent`

Rendered at the bottom of every page. Shows the build version (from `environment.ts`) and the current date/time. Version is injected at build time from the `APP_VERSION` environment variable.

### `RunStatsChipsComponent`

Inline chip bar showing pass/fail/new counts for a run. Used in both `ProjectsListComponent` (latest run) and `SuiteDetailComponent` (run list). Renders `.chip` elements, hiding chips whose count is 0.

### `SearchFieldComponent`

Reusable search input with a clear button. Emits a debounced `valueChanges` observable. Used in `ProjectsListComponent`, `SuiteDetailComponent` (baselines tab), and `RunDetailComponent`.

### `ImageViewerComponent`

Full-screen modal (`MatDialog`) for inspecting a test's images. Receives the full test list and an initial test index and slot on open. Features:

**Slots** — four views selectable via tabs in the modal footer:
- **Baseline** — the stored reference image
- **Comparison** — the new screenshot from this run
- **Diff** — the ImageMagick diff overlay
- **Compare** — split-screen overlay of baseline vs comparison (or diff), with a draggable divider

**Navigation**
- ArrowLeft / ArrowRight — cycle slots (Baseline → Comparison → Diff → Compare → Baseline)
- ArrowUp / ArrowDown — navigate between tests in the run
- Escape — close modal

**Compare mode**
- A draggable vertical divider splits the canvas left/right between baseline (left) and the right-side image
- Mouse drag and touch drag both move the divider
- A **vs** toggle button switches the right-side image between Comparison and Diff

**Loading state** — each slot transition shows a shimmer skeleton (`#1e293b` background with cyan sweep) until the image fires its `load` event. `onImgError` also dismisses the skeleton to avoid lingering placeholders on broken images. The `viewerLoaded` signal resets whenever `testIndex` or `slot` changes.

## Services

### `InspectreApiService`

Located at `frontend/src/app/core/api/inspectre-api.service.ts`. All HTTP calls go through this service. Returns `Observable<T>` — route components convert to signals with `toSignal()`.

| Method | HTTP | Path |
|--------|------|------|
| `projects()` | GET | `/api/projects/` |
| `suite(proj, suite)` | GET | `/api/projects/:proj/suites/:suite/` |
| `run(proj, suite, seq)` | GET | `/api/projects/:proj/suites/:suite/runs/:seq/` |
| `testHistory(proj, suite, key)` | GET | `/api/projects/:proj/suites/:suite/tests/:key/` |
| `testsBulk(ids)` | POST | `/api/tests/bulk/` |
| `baseline(key)` | GET | `/api/baselines/:key/` |
| `setBaseline(testId)` | POST | `/api/tests/:id/set-baseline/` |

Base path `/api` is a private `readonly apiBase` on the service. In production the SPA is same-origin so relative paths work without configuration.

### `SortStateService`

Persists and restores table sort column + direction to `localStorage`. Key pattern: `inspectre.sort.<table-id>`. Used by `ProjectsListComponent`, `SuiteDetailComponent`, and `RunDetailComponent` so sort preferences survive page reloads.

## Interceptors

### `ErrorInterceptor`

Wraps every `HttpClient` request. On a non-2xx response it opens a `MatSnackBar` with the status message (or "Cannot reach Inspectre" for network errors) and rethrows so the route component can fall back to an empty state.

```yaml
duration: 5000 ms
panelClass: 'error-snack'
```

### `LoadingInterceptor`

Wraps every `HttpClient` request. Calls `LoadingService.increment()` before the request and `LoadingService.decrement()` (via `finalize`) when it completes, errors, or is cancelled. `LoadingService` exposes a `loading: Signal<boolean>` (`count() > 0`) that components can use to show a global loading indicator. Wired alongside `ErrorInterceptor` in `app.config.ts`.

## Image loading skeletons

All image sites use two global CSS state classes from `styles.scss`:

- `.img-skeleton` — dark slate background (`#1e293b`) with a cyan-tinted shimmer sweep (`rgba(56,189,248,0.08)`, 1.6 s, `linear`). The child `<img>` is `opacity: 0`.
- `.img-loaded` — transparent background, no shimmer, `img { opacity: 1 }`.

Elements start with `img-skeleton` and switch to `img-loaded` on the `(load)` event. `(error)` also triggers the switch so broken images don't linger as skeletons.

**Thumbnails** — the `thumbLoaded` signal in `RunDetailComponent` tracks loaded URLs in a `Set<string>`. Using the URL as key means a cached image URL that fires `load` on reuse is handled correctly.

**Image viewer** — `viewerLoaded = signal<boolean>(false)` resets to `false` in an `effect()` whenever `testIndex()` or `slot()` changes, so each navigation shows the skeleton again until the new image loads.

## TypeScript models (`frontend/src/app/core/models/api.ts`)

These interfaces mirror the DRF serializers exactly. If a field name diverges from the serializer output, the SPA breaks at runtime. The `passed` field on `TestRow` (SPA) and the `pass` field on the legacy API are parallel — do not unify them.

```typescript
export interface Project {
  id: number;
  name: string;
  slug: string;
  suites: SuiteSummary[];
}

export interface SuiteSummary {
  id: number;
  name: string;
  slug: string;
  latest_run: RunSummary | null;
}

export interface SuiteDetail {
  id: number;
  name: string;
  slug: string;
  project_name: string;
  latest_runs: RunSummary[];
  baselines: Baseline[];
}

export interface RunSummary {
  id: number;
  sequential_id: number;
  created_at: string;   // ISO-8601
  passing: number;
  failing: number;
  unbaselined: number;
}

export interface RunDetail {
  id: number;
  sequential_id: number;
  created_at: string;
  project_name: string;
  tests: TestRow[];
}

export interface TestRow {
  id: number;
  name: string;
  browser: string;
  size: string;
  source_url: string;   // empty string when not set, never null
  status: string;
  diff: number;
  passed: boolean;
  key: string;
  is_baseline_source: boolean; // this test is the producer of the current Baseline for its key
  has_baseline: boolean;       // drives the "New baseline" chip
  fuzz_level: string;
  highlight_colour: string;
  crop_area: string;    // empty string when not set, never null
  screenshot_url: string | null;
  baseline_url: string | null;
  diff_url: string | null;
  screenshot_thumb_url: string | null;
  baseline_thumb_url: string | null;
  diff_thumb_url: string | null;
  created_at: string;
}

export interface TestHistoryEntry {
  id: number;
  run_id: number;
  run_sequential_id: number;
  run_created_at: string;
  original_passed: boolean | null;
  is_new_baseline: boolean | null;
  status: string;
  screenshot_thumb_url: string | null;
}

export interface TestHistory {
  key: string;
  name: string;
  browser: string;
  size: string;
  project_name: string;
  suite_slug: string;
  runs: TestHistoryEntry[];
}

export interface Baseline {
  id: number;
  name: string;
  browser: string;
  size: string;
  key: string;
  screenshot_url: string | null;
  thumbnail_url: string | null;
  created_at: string;
}
```

## Wiring (`app.config.ts`)

```typescript
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideZonelessChangeDetection(),
    provideRouter(routes),
    provideHttpClient(withFetch(), withInterceptors([errorInterceptor, loadingInterceptor])),
    provideAnimationsAsync(),
  ],
};
```

`provideZonelessChangeDetection()` — Angular zoneless mode. Change detection is signal-driven; there is no `NgZone` and no `zone.js` in the bundle.
