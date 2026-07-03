<p align="center">
  <img src="https://raw.githubusercontent.com/wvankuipers/inspectre/main/frontend/public/favicon.svg" width="80" alt="Inspectre logo">
</p>

<h1 align="center">Inspectre</h1>

<p align="center">
  <a href="https://github.com/wvankuipers/inspectre/actions/workflows/ci.yml"><img src="https://github.com/wvankuipers/inspectre/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://codecov.io/gh/wvankuipers/inspectre"><img src="https://codecov.io/gh/wvankuipers/inspectre/graph/badge.svg" alt="Coverage"></a>
  <img src="https://img.shields.io/badge/dynamic/regex?url=https%3A%2F%2Fraw.githubusercontent.com%2Fwvankuipers%2Finspectre%2Fmain%2FVERSION&search=%5E(.%2B)%24&replace=%241&label=version&color=38bdf8" alt="Version">
  <a href="https://hub.docker.com/r/wvankuipers/inspectre"><img src="https://img.shields.io/docker/image-size/wvankuipers/inspectre/api-latest?label=api%20image" alt="API image size"></a>
  <a href="https://hub.docker.com/r/wvankuipers/inspectre"><img src="https://img.shields.io/docker/image-size/wvankuipers/inspectre/spa-latest?label=spa%20image" alt="SPA image size"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License"></a>
</p>

**Visual regression testing as a service.** CI pipelines POST screenshots to Inspectre; Inspectre diffs them against approved baselines and reports pass/fail. A web UI lets your team review failures, inspect diff images, and promote new baselines with one click.

Built as a modern Python/Angular rewrite of the original [Spectre](https://github.com/wearefriday/spectre) Rails app.

---

## How it works

```text
CI job
  └─ POST /runs          → creates a run
  └─ POST /tests         → uploads screenshot, returns immediately (~50 ms)
  └─ GET  /tests/:id/status  → poll until status == "done"

Celery worker (async)
  └─ ImageMagick compare vs stored baseline
  └─ Stores diff image + thumbnails to S3
  └─ Marks test passed / failed

Human
  └─ Opens http://localhost:4200
  └─ Reviews diff images, clicks "Set as baseline" to accept regressions
```

The first submission for any (project, suite, name, browser, size) combination has no baseline — Inspectre self-baselines and marks it `is_new_baseline: true`. Subsequent submissions compare against that baseline.

---

## Architecture

| Layer          | Technology                                                |
| -------------- | --------------------------------------------------------- |
| API server     | Python, Django, Django REST Framework                     |
| Task queue     | Celery + Valkey (Redis-protocol broker)                   |
| Web UI         | Angular, standalone/zoneless components, Angular Material |
| Database       | PostgreSQL                                                |
| Object storage | S3-compatible — MinIO in dev, AWS S3 in prod              |
| Serving        | gunicorn (API) + nginx (SPA + reverse proxy)              |
| Orchestration  | Docker Compose                                            |

### Domain model

```text
Project ──▶ Suite ──▶ Run ──▶ Test
                  └─▶ Baseline  (one per test "key", lives on the Suite)
```

- **Project** — top-level grouping, e.g. "Acme Marketing Site"
- **Suite** — category of tests inside a project, e.g. "Desktop" or "Mobile"
- **Run** — one CI execution of a suite; the last 5 runs are kept per suite
- **Test** — one screenshot submission; carries diff %, pass/fail, and S3 image URLs
- **Baseline** — the accepted-good screenshot for a key; updated automatically on first pass or manually via the UI

### Image pipeline

`POST /tests` returns in ~50 ms. The heavy work runs in a Celery worker:

1. Download staged upload from S3
2. Optionally crop to a specified region
3. Pad both images to the same canvas
4. `imagemagick compare -metric AE` → diff pixel count → diff percentage
5. Upload original, baseline snapshot, diff overlay, and 300 px JPEG thumbnails
6. Upsert Baseline if passing; set `status = "done"`

### API surfaces

Two URL namespaces:

- **`/api/*`** — SPA endpoints; can evolve freely
- **Legacy (un-prefixed)** — frozen contract for CI clients: `POST /runs`, `POST /tests`, `GET /tests/:id/status`, `PATCH /tests/:id`, `GET /baselines/:key.png`, `GET /baselines/:key.json`

### Docker images

| Image                                                                     | Tags                          |
| ------------------------------------------------------------------------- | ----------------------------- |
| [`wvankuipers/inspectre`](https://hub.docker.com/r/wvankuipers/inspectre) | `api-latest`, `api-<version>` |
| [`wvankuipers/inspectre`](https://hub.docker.com/r/wvankuipers/inspectre) | `spa-latest`, `spa-<version>` |

### Documentation

- [Overview](docs/overview.md)
- [API reference](docs/api.md)
- [Data model](docs/data-model.md)
- [Image diffing](docs/image-diffing.md)
- [Storage & thumbnails](docs/storage-and-thumbnails.md)
- [Deployment & config](docs/deployment-and-config.md)
- [UI](docs/ui.md)
- [Tests & fixtures](docs/tests-and-fixtures.md)
- [Architecture decisions](docs/decisions.md)

---

## Development

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- `make`

### First-time setup

```bash
cp deploy/.env.example .env
# Edit .env — at minimum set ADMIN_PASSWORD
make build
make up
make migrate
```

Services:

| Service       | URL                                                   |
| ------------- | ----------------------------------------------------- |
| SPA           | http://localhost:4200                                 |
| API           | http://localhost:8000                                 |
| Django admin  | http://localhost:8000/admin                           |
| MinIO console | http://localhost:9001 (login: `minio` / `miniominio`) |

The SPA's nginx reverse-proxies `/api`, `/runs`, `/tests`, `/baselines`, and `/admin` to the API container — everything is same-origin from the browser.

### Seed demo data

```bash
make seed
```

Populates three projects with runs, pass/fail tests, and baselines so you can explore the UI without a real CI pipeline.

### Common commands

| Command                       | What it does                               |
| ----------------------------- | ------------------------------------------ |
| `make up`                     | Start the stack                            |
| `make down`                   | Stop the stack (volumes preserved)         |
| `make test`                   | All backend + frontend tests               |
| `make test-fast`              | Backend only, no ImageMagick (~1 s)        |
| `make test-slow`              | Backend including image diff tests         |
| `make lint` / `make lint-fix` | Ruff + Angular ESLint                      |
| `make migrate`                | Run Django migrations inside api container |
| `make shell-api`              | Django shell inside api container          |
| `make reset`                  | Nuke and rebuild everything from scratch   |
| `make perf`                   | Performance stress test (needs `make up`)  |

### Rebuilding after code changes

**Backend / worker:**

```bash
docker compose build api worker && docker compose up -d api worker
```

**Frontend:**

```bash
docker compose build spa && docker compose up -d spa
```

---

## Production deployment

### Environment variables

| Variable                    | Required | Notes                                                                        |
| --------------------------- | -------- | ---------------------------------------------------------------------------- |
| `DJANGO_SECRET_KEY`         | yes      | Generate with `python -c 'import secrets; print(secrets.token_urlsafe(50))'` |
| `DEBUG`                     | no       | `0` in prod                                                                  |
| `ALLOWED_HOSTS`             | yes      | Comma-separated hostnames                                                    |
| `CORS_ALLOWED_ORIGINS`      | no       | Comma-separated origins; empty means same-origin only                        |
| `DATABASE_URL`              | yes      | Full postgres DSN                                                            |
| `S3_BUCKET_NAME`            | yes      | Must exist before first run                                                  |
| `S3_REGION`                 | yes      | AWS region or any value for MinIO                                            |
| `S3_ENDPOINT_URL`           | no       | Set for MinIO; omit for AWS S3                                               |
| `S3_ACCESS_KEY_ID`          | yes      | AWS key or MinIO root user                                                   |
| `S3_SECRET_ACCESS_KEY`      | yes      | AWS secret or MinIO root password                                            |
| `S3_PUBLIC_BASE_URL`        | no       | CDN prefix for browser-reachable image URLs                                  |
| `ADMIN_USERNAME`            | no       | Default: `admin`                                                             |
| `ADMIN_PASSWORD`            | no       | If unset, `ensure_admin_user` skips bootstrap (no admin account created)     |
| `REDIS_URL`                 | no       | Valkey/Redis broker; default `redis://localhost:6379/0`                      |
| `CELERY_WORKER_CONCURRENCY` | no       | Parallel image pipelines per worker; default `2`                             |
| `GUNICORN_WORKERS`          | no       | API server processes; default `3`                                            |
| `IMAGE_DIFF_THRESHOLD`      | no       | Diff % to count as failure; default `0.1`                                    |
| `RUN_RETENTION_PER_SUITE`   | no       | Max runs kept per suite; default `5`                                         |

### Deploy

```bash
# First deploy
cp deploy/.env.example .env   # fill in production values
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml exec api python manage.py migrate

# Subsequent deploys
docker compose -f deploy/docker-compose.yml build api spa worker
docker compose -f deploy/docker-compose.yml up -d api spa worker
docker compose -f deploy/docker-compose.yml exec api python manage.py migrate
```

### Production checklist

- [ ] `DEBUG=0`
- [ ] `DJANGO_SECRET_KEY` is unique and random
- [ ] `ALLOWED_HOSTS` includes the production hostname
- [ ] S3 bucket exists; credentials have `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- [ ] Database backed up before running migrations
- [ ] `S3_PUBLIC_BASE_URL` set if serving images through a CDN

---

## Submitting screenshots from CI

```bash
# 1. Create a run
RUN=$(curl -s -X POST http://inspectre.example.com/runs \
  -d "project=My App&suite=Desktop" | jq -r .id)

# 2. Submit a screenshot (returns immediately with status=pending)
TEST_ID=$(curl -s -X POST http://inspectre.example.com/tests \
  -F "test[run_id]=$RUN" \
  -F "test[name]=Homepage" \
  -F "test[browser]=Chrome" \
  -F "test[size]=1440" \
  -F "test[screenshot]=@homepage.png" | jq -r .id)

# 3. Poll for result
while true; do
  STATUS=$(curl -s http://inspectre.example.com/tests/$TEST_ID/status | jq -r .status)
  [ "$STATUS" = "done" ] || [ "$STATUS" = "failed" ] && break
  sleep 1
done
```

The `pass` field in the final response is `true` if the diff percentage is below the threshold.

---

## CI/CD

The GitHub Actions workflow (`.github/workflows/ci.yml`) runs lint and tests on every push and pull request to `main`, then builds and pushes multi-arch Docker images to Docker Hub on successful merges to `main`.

### Required repository secrets

| Secret               | How to obtain                                               |
| -------------------- | ----------------------------------------------------------- |
| `DOCKERHUB_USERNAME` | Your Docker Hub username                                    |
| `DOCKERHUB_TOKEN`    | Docker Hub → Account Settings → Security → New Access Token |

Set these under **Settings → Secrets and variables → Actions** in the GitHub repository.

### Published images

| Image                            | Tag            |
| -------------------------------- | -------------- |
| `<DOCKERHUB_USERNAME>/inspectre` | `api-latest`   |
| `<DOCKERHUB_USERNAME>/inspectre` | `api-$VERSION` |
| `<DOCKERHUB_USERNAME>/inspectre` | `spa-latest`   |
| `<DOCKERHUB_USERNAME>/inspectre` | `spa-$VERSION` |

---

## License

See [LICENSE](LICENSE).
