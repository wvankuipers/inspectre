# Deployment & Configuration

## Stack

- **Backend:** Python 3.12 / Django 5.1 / gunicorn
- **Task queue:** Celery 5.4 workers, Valkey 8 broker
- **Frontend:** Angular 22 SPA served by nginx
- **Database:** PostgreSQL 16
- **Object storage:** S3-compatible (MinIO in dev, AWS S3 in prod)
- **Orchestration:** Docker Compose (single-host), see `deploy/docker-compose.yml`

---

## Local Development

### Prerequisites

- Docker Desktop (or Docker Engine + Compose plugin)
- `make`

### First-time setup

```bash
cp deploy/.env.example .env
# Edit .env — set DJANGO_SECRET_KEY, ADMIN_PASSWORD
make up
make migrate
```

Services start at:

| Service       | URL                          |
|---------------|------------------------------|
| SPA           | http://localhost:4200        |
| API           | http://localhost:8000        |
| Django admin  | http://localhost:8000/admin  |
| MinIO console | http://localhost:9001        |

### Useful make targets

| Target           | What it does                              |
|------------------|-------------------------------------------|
| `make up`        | Start all services                        |
| `make migrate`   | Run Django migrations inside api container|
| `make test`      | All tests (backend + frontend)            |
| `make test-fast` | Backend only, no ImageMagick              |
| `make test-slow` | Backend including image diff tests        |
| `make lint`      | Ruff + Angular ESLint                     |
| `make lint-fix`  | Auto-fix both                             |

### Rebuilding after code changes

**Backend:** `docker compose -f deploy/docker-compose.yml build api worker && docker compose -f deploy/docker-compose.yml up -d api worker`

**Frontend:** `docker compose -f deploy/docker-compose.yml build spa && docker compose -f deploy/docker-compose.yml up -d spa`

---

## Environment Variables

All runtime config is passed via `.env` (dev) or environment variables (prod).

| Variable                     | Required | Default                           | Notes                                                                                         |
|------------------------------|----------|-----------------------------------|-----------------------------------------------------------------------------------------------|
| `DJANGO_SECRET_KEY`          | yes      | `dev-only-...`                    | Generate with `python -c 'import secrets; print(secrets.token_urlsafe(50))'`                  |
| `DEBUG`                      | no       | `0`                               | Set `1` in dev only                                                                           |
| `ALLOWED_HOSTS`              | yes      | `localhost,127.0.0.1`             | Comma-separated list of valid hostnames                                                       |
| `CORS_ALLOWED_ORIGINS`       | no       | `` (empty)                        | Set in split-host deployments only                                                            |
| `DATABASE_URL`               | yes      | postgres://inspectre:inspectre@db | Full postgres DSN                                                                             |
| `S3_BUCKET_NAME`             | yes      | `inspectre-screenshots`           | Bucket must exist before first run                                                            |
| `S3_REGION`                  | yes      | `us-east-1`                       | AWS region or any value for MinIO                                                             |
| `S3_ENDPOINT_URL`            | no       | —                                 | Set to MinIO URL in dev; omit for AWS S3                                                      |
| `S3_ACCESS_KEY_ID`           | yes      | —                                 | AWS access key or MinIO root user                                                             |
| `S3_SECRET_ACCESS_KEY`       | yes      | —                                 | AWS secret key or MinIO root password                                                         |
| `S3_PUBLIC_BASE_URL`         | no       | —                                 | Full URL prefix for browser-reachable file links (e.g. `http://localhost:9000/inspectre-screenshots` in dev, `https://cdn.example.com` in prod) |
| `ADMIN_USERNAME`             | no       | `admin`                           | Django admin username                                                                         |
| `ADMIN_PASSWORD`             | no       | —                                 | Django admin password; if unset, `ensure_admin_user` skips bootstrap (no admin account created) |
| `IMAGE_DIFF_THRESHOLD`       | no       | `0.1`                             | % diff to count as failure                                                                    |
| `RUN_RETENTION_PER_SUITE`    | no       | `5`                               | Max runs kept per suite (older pruned)                                                        |
| `DEFAULT_FUZZ_LEVEL`         | no       | `30%`                             | ImageMagick fuzz level                                                                        |
| `IMAGEMAGICK_TIMEOUT_SECONDS`| no       | `60`                              | Per-command timeout for ImageMagick subprocesses                                              |
| `GUNICORN_WORKERS`           | no       | `3`                               | Number of gunicorn worker processes                                                           |
| `REDIS_URL`                  | no       | `redis://localhost:6379/0`        | Valkey/Redis broker URL; use `redis://valkey:6379/0` in Docker Compose                       |
| `CELERY_WORKER_CONCURRENCY`  | no       | `2`                               | Parallel ImageMagick pipelines per worker container                                           |

---

## Production Deployment

### Checklist

- [ ] `DEBUG=0`
- [ ] `DJANGO_SECRET_KEY` set to a unique random value
- [ ] `ALLOWED_HOSTS` includes the production hostname
- [ ] Database backed up before `make migrate`
- [ ] S3 bucket exists and IAM credentials have `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- [ ] `S3_PUBLIC_BASE_URL` set if serving files through a CDN

### First deploy

```bash
# On the server, in the project root:
cp deploy/.env.example .env
# Edit .env for production values
docker compose -f deploy/docker-compose.yml pull  # or build
docker compose -f deploy/docker-compose.yml up -d
docker compose -f deploy/docker-compose.yml exec api python manage.py migrate
```

### Subsequent deploys

```bash
docker compose -f deploy/docker-compose.yml build api spa worker
docker compose -f deploy/docker-compose.yml up -d api spa worker
docker compose -f deploy/docker-compose.yml exec api python manage.py migrate
```

### Database migrations

Migrations run inside the container against the live database. Always back up first in production:

```bash
docker compose -f deploy/docker-compose.yml exec db pg_dump -U inspectre inspectre > backup.sql
docker compose -f deploy/docker-compose.yml exec api python manage.py migrate
```
