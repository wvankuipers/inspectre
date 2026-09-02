# Inspectre — Claude Code Instructions

## Required Workflow

1. **Always use the superpowers skill** — invoke the relevant `superpowers:*` skill before starting any task. Use `superpowers:brainstorming` for new features, `superpowers:systematic-debugging` for bugs, `superpowers:subagent-driven-development` for implementation.

2. **Always use the subagent approach to implement changes** — never implement directly in the main session. Use `superpowers:subagent-driven-development` to dispatch a fresh subagent per task with spec and code quality review gates.

3. **Always test changes, test-first for bug fixes** — for bug fixes, write a failing test that reproduces the bug before writing the fix. All code changes must be covered by tests. Run the relevant test suite after every change. Never mark a task done with failing tests.

4. **Always verify in browser using Chrome MCP** — after rebuilding the SPA container, use the Chrome DevTools MCP to navigate to `http://localhost:4200` and take a screenshot to confirm the UI looks correct before reporting the task complete.

5. Never load assets, for example fonts or icons, via the Google CDN. Always use inline/self hosted assets.

6. **`make test` and `make lint` must pass locally before finishing a branch or opening a PR.** Do not hand off or open a PR with either failing.

7. **Never commit or push directly to `main`.** All changes go through a feature branch and a PR.

8. **Run `make lint-fix` (or the equivalent formatter/linter) before marking any task complete.** No task is done with outstanding lint or formatting violations.

9. **Update relevant documentation when finishing a task.** If a change alters architecture, API surface, routes, models, or workflow, update `CLAUDE.md` and/or `docs/` in the same task — don't leave docs stale.

---

## Architecture Overview

Visual regression testing SaaS. CI pipelines upload screenshots directly via the REST API; the backend diffs them against approved baselines; the SPA lets users review results and promote screenshots to baselines.

---

## Backend

**Language / Framework:** Python 3.13+, Django 6.1, Django REST Framework

**Single app:** `core` — all models, views, serializers, and services live here.

### Models

| Model      | Purpose                                                                              |
| ---------- | ------------------------------------------------------------------------------------ |
| `Project`  | Top-level container; name auto-slugified                                             |
| `Suite`    | Groups runs; tracks `next_run_seq` for atomic sequencing                             |
| `Run`      | One CI test run; `sequential_id` assigned atomically in `save()`                     |
| `Test`     | Individual screenshot result; key derived from (project, suite, name, browser, size); `original_passed` is a tamper-proof snapshot of the initial pass/fail. Also carries the async processing state machine — `status`, `process_attempts`, `processing_claim` (fencing token), `is_new_baseline`, `fuzz_level`, `highlight_colour`, `crop_area` — and six screenshot `FileField`s (original/baseline/diff + their thumbnails) |
| `Baseline` | Approved reference screenshot; FK'd to `Suite`, and to `Test` via a `SET_NULL` FK kept for informational purposes only; has its own `screenshot`/`thumbnail` `FileField`s (not just a key reference) |
| `ProcessingQueueTest` | Proxy model over `Test` used only to give the Django admin a read-only view of tests still processing |

### API surfaces

Two URL surfaces, both unauthenticated (`AllowAny`):

**SPA endpoints** (`/api/*`) — can evolve freely:

- `GET /api/projects/`
- `GET /api/projects/<slug>/suites/<slug>/`
- `GET /api/projects/<slug>/suites/<slug>/runs/<seq>/`
- `GET /api/projects/<slug>/suites/<slug>/tests/<key>/` — cross-run pass/fail history for a test
- `POST /api/tests/bulk/` — fetch fresh test rows for a set of ids (polling)
- `POST /api/tests/<id>/set-baseline/`
- `GET /api/baselines/<key>/`

**Legacy endpoints** (un-prefixed, frozen — the Client API implementation calls these):

- `POST /runs` — create run (find-or-create project + suite)
- `POST /tests` — create test, enqueue diff via Celery, return `status=pending`
- `GET /tests/<id>/status` — poll for async result (`status=done|failed`)
- `PATCH /tests/<id>` — update test (set baseline); `PUT` is also accepted
- `GET /baselines/<key>.png` / `GET /baselines/<key>.json`

**Infrastructure** (neither SPA nor legacy Client API surface):

- `GET /healthz/` — dependency-free health check for Kubernetes liveness/readiness probes

### Image pipeline (async, Celery)

`POST /tests` stages the uploaded screenshot to S3 under a staging key, enqueues a `process_test` Celery task, and returns immediately with `status=pending`. The worker downloads the staged upload and runs the diff: crop (only if `crop_area` is set) → compare against baseline via ImageMagick (`compare`) → generate diff overlay and JPEG thumbnails → persist results to S3 → update the Test record → delete the staging object. If no baseline exists yet, this is a distinct "first upload" path that stores the screenshot and thumbnail without comparing/diffing. `process_test` also has correctness machinery for concurrent/duplicate delivery: a Postgres advisory lock, a `processing_claim` fencing token, and a `PROCESS_TEST_MAX_ATTEMPTS` retry cap with requeue-on-lock-contention.

### Storage

All images in S3-compatible storage (MinIO in dev, AWS S3 in prod). Bucket: `inspectre-screenshots`. Path patterns:

- `screenshots/{test_id}/{original|baseline|diff}.png`, `screenshots/{test_id}/{thumb-300|thumb-300-baseline|thumb-300-diff}.jpg`
- `baselines/{key}/{screenshot.png|thumb-300.jpg}` — the `Baseline` model's own copies
- `screenshots/staging/{test_id}/upload.png` — transient staging object, deleted after processing

### Key settings (`backend/inspectre/settings.py`)

| Variable                      | Default | Purpose                          |
| ----------------------------- | ------- | -------------------------------- |
| `IMAGE_DIFF_THRESHOLD`        | `0.1`   | Pass/fail cutoff                 |
| `RUN_RETENTION_PER_SUITE`     | `5`     | Max runs to keep per suite       |
| `DEFAULT_FUZZ_LEVEL`          | `"30%"` | ImageMagick fuzz                 |
| `DEFAULT_HIGHLIGHT_COLOUR`    | `"ff0000"` | Diff overlay highlight colour  |
| `THUMBNAIL_WIDTH`             | `300`   | Thumbnail width (px)             |
| `THUMBNAIL_JPEG_QUALITY`      | `90`    | Thumbnail JPEG quality           |
| `IMAGEMAGICK_TIMEOUT_SECONDS` | `60`    | Timeout for ImageMagick commands |
| `PROCESS_TEST_MAX_ATTEMPTS`   | `3`     | Retry cap for `process_test` before giving up |

### Auth

No API auth. Django admin (`/admin/`) uses session auth with a shared staff user bootstrapped via `ensure_admin_user` management command using `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars.

### Backend tests

Run with: `cd backend && pytest` (or `make test-fast` / `make test-slow`)

- **Fast** (`make test-fast`, ~1 s): serializers, SPA API, admin, models, health, settings, Celery task fencing/retry logic — no real ImageMagick
- **Slow** (`make test-slow`, ~5 s): legacy API, screenshot comparison, baseline upsert, seed — real `convert`/`compare` shell-outs
- `make test-fast`/`make test-slow` run curated packs (see `Makefile`), not the full suite — bare `pytest` also picks up S3/IAM-auth test files (`test_s3*.py`, `test_iam_*.py`) that neither make target runs
- Framework: pytest + pytest-django + factory-boy; parallel via `pytest -n auto`
- Lint: `ruff check` (rules E, F, I, B, UP, DJ; line length 120)

---

## Frontend

**Framework:** Angular, standalone/zoneless components, Angular Material
**Testing:** Vitest + jsdom
**Lint:** Angular ESLint + Prettier

Run tests: `cd frontend && npm test`

### Routes

All routes nest under a root `AppShellComponent` (toolbar/breadcrumb/loading indicator) with a `** → /projects` catch-all redirect.

| Route                                                    | Component                                              |
| --------------------------------------------------------- | ------------------------------------------------------ |
| `/projects`                                                | `ProjectsListComponent` — flattened project+suite rows |
| `/projects/:projectSlug/suites/:suiteSlug`                 | `SuiteDetailComponent` — latest 5 runs + baselines     |
| `/projects/:projectSlug/suites/:suiteSlug/runs/:seqId`     | `RunDetailComponent` — test table with thumbnails      |
| `/projects/:projectSlug/suites/:suiteSlug/tests/:key`      | `TestDetailComponent` — cross-run pass/fail history for one test |

### Key files

| Path                                                        | Purpose                                                          |
| ------------------------------------------------------------ | ---------------------------------------------------------------- |
| `frontend/src/app/core/api/inspectre-api.service.ts`         | `InspectreApiService` — HTTP client for all API calls             |
| `frontend/src/app/core/services/sort-state.service.ts`      | Persists table sort to `localStorage` (keys: `inspectre.sort.*`) |
| `frontend/src/app/core/interceptors/error.interceptor.ts`   | Shows snackbar on HTTP errors                                    |
| `frontend/src/app/core/interceptors/loading.interceptor.ts` | Drives `loading.service.ts` counter for the global loading indicator |
| `frontend/src/app/core/models/api.ts`                       | TypeScript types mirroring DRF serializers                       |
| `frontend/src/styles.scss`                                  | Global styles: Material theme, `.inspectre-card`, chip classes   |

Shared UI components live under `frontend/src/app/core/components/` — `app-shell`, `app-toolbar`, `breadcrumb`, `image-viewer`, `page-footer`, `run-stats-chips`, `search-field`. Reuse these rather than adding new ad-hoc UI.

### Visual conventions

- Background: `#f1f5f9` (slate-100)
- Toolbar: `#0f172a` (navy)
- Accent: `#38bdf8` (sky-400, Angular Material cyan palette)
- Cards: `.inspectre-card` class (white, 10 px radius, subtle shadow)
- Status chips: `<span class="chip chip-pass|chip-fail|chip-new|chip-none">`. `chip-new-baseline` also exists but is defined locally in `run-detail.component.scss`, not in the global stylesheet.

---

## Infrastructure

**Compose file:** `deploy/docker-compose.yml`

| Service      | Purpose                                                | Port                 |
| ------------ | ------------------------------------------------------ | -------------------- |
| `api`        | Django / gunicorn                                      | 8000                 |
| `spa`        | nginx serving Angular bundle + reverse-proxy           | 4200                 |
| `db`         | PostgreSQL                                             | —                    |
| `valkey`     | Redis-protocol broker for Celery                       | —                    |
| `worker`     | Celery worker (`celery -A inspectre worker`) — runs the image diff pipeline | — |
| `minio`      | S3-compatible image storage (dev)                      | 9000, 9001 (console) |
| `minio-init` | Creates `inspectre-screenshots` bucket on first boot   | —                    |
| `api-dev`    | api + dev tools, bind-mounted source (`--profile dev`) | —                    |
| `spa-dev`    | Node container for `npm` (`--profile dev`)             | —                    |

**Rebuild SPA after any frontend change:**

```
docker compose build spa && docker compose up -d spa
```

**Useful make targets:**

```
make up             # start all services
make down           # stop and remove all containers (preserves volumes)
make logs           # tail the api service's logs
make shell-api      # open a Django shell inside the api container
make test           # all tests (backend fast+slow + frontend)
make test-fast      # backend only, no ImageMagick
make test-slow      # backend including image diff tests
make test-frontend  # Angular Vitest
make lint           # ruff + angular-eslint
make lint-fix       # auto-fix both
make migrate        # run Django migrations
make seed           # load demo data (wipes existing demo data first)
make clean          # stop containers and remove volumes — DESTROYS local data
```
