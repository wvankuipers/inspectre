# Deployment & Configuration

## Stack

- **Backend:** Python / Django / gunicorn
- **Task queue:** Celery workers, Valkey broker
- **Frontend:** Angular SPA served by nginx
- **Database:** PostgreSQL
- **Object storage:** S3-compatible (SeaweedFS in dev, AWS S3 in prod)
- **Orchestration:** Docker Compose (single-host), see `deploy/docker-compose.yml`

The `spa` image renders its nginx config from `frontend/nginx.spa.conf.template`
at container start (via the base image's built-in envsubst-on-templates
entrypoint), substituting `API_UPSTREAM` and `RESOLVER_ADDRESS`. Everything
else in the config is static.

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
| S3 API        | http://localhost:9000 (no web console) |

### Docker Compose services (`deploy/docker-compose.yml`)

| Service      | Purpose                                                                     | Port                 |
|--------------|------------------------------------------------------------------------------|----------------------|
| `api`        | Django / gunicorn                                                           | 8000                 |
| `spa`        | nginx serving Angular bundle + reverse-proxy                                | 4200                 |
| `db`         | PostgreSQL                                                                  | —                    |
| `valkey`     | Redis-protocol broker for Celery                                            | —                    |
| `worker`     | Celery worker (`celery -A inspectre worker`) — runs the image diff pipeline | —                    |
| `seaweedfs`  | S3-compatible image storage (dev; `chrislusf/seaweedfs:4.54`, S3 on container port 8333, static identity from `deploy/seaweedfs-s3.json`, volume `seaweedfs-data`) | 9000 (→ 8333) |
| `s3-init`    | boto3 one-shot that creates the `inspectre-screenshots` bucket; idempotent (re-runs against the persisted volume are a no-op) | —                    |
| `api-dev`    | api + dev tools, bind-mounted source (`--profile dev`)                     | —                    |
| `spa-dev`    | Node container for `npm` (`--profile dev`)                                 | —                    |

> **Note:** the dev stack previously used MinIO (`minio/minio`, no longer pullable from Docker Hub) and now uses SeaweedFS, as the production smoke test does. There is no web console, and the bucket is private (presigned URLs only). A local `.env` from the MinIO era must be updated; see the README.

### Useful make targets

| Target              | What it does                                        |
|----------------------|------------------------------------------------------|
| `make up`            | Start all services                                    |
| `make down`          | Stop and remove all containers (preserves volumes)   |
| `make logs`          | Tail the api service's logs                          |
| `make shell-api`     | Open a Django shell inside the api container         |
| `make migrate`       | Run Django migrations inside api container           |
| `make test`          | All tests (backend fast+slow + frontend)             |
| `make test-fast`     | Backend only, no ImageMagick                         |
| `make test-slow`     | Backend including image diff tests                   |
| `make test-frontend` | Angular Vitest                                        |
| `make lint`          | Ruff + Angular ESLint                                 |
| `make lint-fix`      | Auto-fix both                                         |
| `make seed`          | Load demo data (wipes existing demo data first)      |
| `make smoke`         | Boot the production-style stack and run the smoke checks |
| `make clean`         | Stop containers and remove volumes — DESTROYS local data |

### Rebuilding after code changes

**Backend:** `docker compose -f deploy/docker-compose.yml build api worker && docker compose -f deploy/docker-compose.yml up -d api worker`

**Frontend:** `docker compose -f deploy/docker-compose.yml build spa && docker compose -f deploy/docker-compose.yml up -d spa`

---

## Production smoke test

`make smoke` (runs `deploy/smoke/run.sh`) boots the whole stack the way production runs it and checks that it works end to end. It is independent of the dev stack: separate compose project (`inspectre-smoke`), separate file (`deploy/smoke/docker-compose.smoke.yml`), throwaway values in `deploy/smoke/smoke.env`.

**What it boots:** images built from the repo (backend `runtime` target, and the frontend SPA image), then `api`, `worker` (started with the bare `celery` command a typical Helm/Kubernetes worker spec uses), `spa`, Postgres, **SeaweedFS** as the S3 endpoint (a boto3 `s3-init` one-shot creates the bucket), and Valkey with TLS (`rediss://`) and an ACL user, using a throwaway CA and certificate generated per run (never committed). SeaweedFS is used (as in dev) because `minio/minio` is no longer pullable from Docker Hub. Only two host ports are published: **18000** (api) and **18080** (spa, with its `/api` proxy).

**Checks** (`deploy/smoke/checks.sh`):

1. Boot: every service is running and healthy (the `s3-init` one-shot exited 0), nothing is restarting after a settle period, the worker has `RestartCount` 0.
2. `GET /healthz/` on the api returns 200; the SPA serves its index and proxies `/api`.
3. `celery inspect ping` reaches the worker over the TLS/ACL broker.
4. Upload round trip: create a run, upload `fixtures/baseline.png` (worker finishes, `is_new_baseline`), approve it with `PATCH /tests/:id` (`test[baseline]=true`), upload `fixtures/changed.png` under the same key (diffed, `pass=false`), and `GET .../runs/<seq>/validate/` reports `failed`.

The stack is always torn down (`down -v`); on failure container state and logs are printed first.

**Host requirements:** `docker` with the `compose` v2 plugin, `jq`, `openssl`, `curl`. `run.sh` exits with a clear message if one is missing.

**CI gating:** the `smoke` job in `.github/workflows/ci.yml` runs on PRs and `main`. In `.github/workflows/release.yml` a `smoke` matrix (`ubuntu-latest` and `ubuntu-24.04-arm`) runs first and all four `build-*` image jobs `needs: smoke`, so an image is only published if the stack boots and works on both amd64 and arm64. Both jobs have `timeout-minutes: 30` (cold arm runners).

**Valkey ACL:** the smoke Valkey user (`smoke`, with the default user disabled) mirrors the production user's access string: `on ~* &* -@all +@connection +@read +@write +@transaction +@pubsub +@scripting +time`. `+time` is required because kombu >= 5.7 (Celery 5.7) runs Lua scripts that call `redis.call('TIME')`; without it the worker fails with `ACL failure in script ... 'time'` (an unrecoverable worker error, so the smoke run fails). This is the failure class behind the 1.6.2 worker crash (missing Valkey command permissions), so the smoke test now covers it. The smoke ACL is kept in sync with the real one by hand: if the production user's permissions change, update the `valkey` command in `deploy/smoke/docker-compose.smoke.yml` too.

**Not covered** (so a green run says nothing about them): Kubernetes, Helm, Vault, IRSA, AWS IAM auth (`AWS_IAM_AUTH_ENABLED=1`, `credential_provider` broker URL, RDS IAM), real ElastiCache.

---

## Environment Variables

All runtime config is passed via `.env` (dev) or environment variables (prod).

| Variable                     | Required | Default                           | Notes                                                                                         |
|------------------------------|----------|-----------------------------------|-----------------------------------------------------------------------------------------------|
| `DJANGO_SECRET_KEY`          | yes      | `dev-only-...`                    | Generate with `python -c 'import secrets; print(secrets.token_urlsafe(50))'`                  |
| `DEBUG`                      | no       | `0`                               | Set `1` in dev only                                                                           |
| `ALLOWED_HOSTS`              | yes      | `localhost,127.0.0.1`             | Comma-separated list of valid hostnames                                                       |
| `CSRF_TRUSTED_ORIGINS`       | no       | `` (empty)                        | Comma-separated list of scheme+host origins allowed to submit CSRF-protected POSTs, e.g. `https://inspectre.example.com`. Only needed when the browser's origin differs from the origin Django sees (split-host deployments, or a proxy that rewrites `Host`) — see note below |
| `CORS_ALLOWED_ORIGINS`       | no       | `` (empty)                        | Set in split-host deployments only                                                            |
| `DATABASE_URL`               | yes      | postgres://inspectre:inspectre@db | Full postgres DSN                                                                             |
| `S3_BUCKET_NAME`             | yes      | `inspectre-screenshots`           | Bucket must exist before first run                                                            |
| `S3_REGION`                  | yes      | `us-east-1`                       | AWS region or any value for SeaweedFS                                                           |
| `S3_ENDPOINT_URL`            | no       | —                                 | Set to SeaweedFS URL in dev (`http://seaweedfs:8333`); omit for AWS S3 (`s3-init` then skips bucket creation, so the bucket must pre-exist) |
| `S3_ACCESS_KEY_ID`           | yes      | —                                 | AWS access key or SeaweedFS dev key (`devaccess`)                                                           |
| `S3_SECRET_ACCESS_KEY`       | yes      | —                                 | AWS secret key or SeaweedFS dev secret (`devsecretkey`)                                                       |
| `S3_PUBLIC_BASE_URL`         | no       | —                                 | Browser-reachable origin used to derive the presigning endpoint (e.g. `http://localhost:9000/inspectre-screenshots` in dev, so presigned URLs are signed against `http://localhost:9000` instead of the container-internal SeaweedFS endpoint; omit in prod where the real S3 endpoint is already browser-reachable). SigV4 signs the request's `Host` header (`X-Amz-SignedHeaders=host`), so setting this to a CDN origin does not by itself make presigned URLs work through that CDN — the CDN must forward requests to S3 preserving the exact viewer host and query string, or you need CloudFront signed URLs/cookies instead of S3 presigning |
| `ADMIN_USERNAME`             | no       | `admin`                           | Django admin username                                                                         |
| `ADMIN_PASSWORD`             | no       | —                                 | Django admin password; if unset, `ensure_admin_user` skips bootstrap (no admin account created) |
| `AWS_REGION`                 | no       | `us-east-1`                       | AWS region used for RDS IAM token signing (`core/db_backends/iam_postgres/base.py`) and ElastiCache SigV4 signing (`core/cache_backends/iam_credential_provider.py`) when `AWS_IAM_AUTH_ENABLED=1`. Must be set to the region the RDS/ElastiCache resources actually live in, or IAM auth token generation will fail |
| `IMAGE_DIFF_THRESHOLD`       | no       | `0.1`                             | % diff to count as failure                                                                    |
| `RUN_RETENTION_PER_SUITE`    | no       | `5`                               | Max runs kept per suite (older pruned)                                                        |
| `DEFAULT_FUZZ_LEVEL`         | no       | `30%`                             | ImageMagick fuzz level                                                                        |
| `DEFAULT_HIGHLIGHT_COLOUR`   | no       | `ff0000`                          | Hex colour used to highlight diffs                                                             |
| `PROCESS_TEST_MAX_ATTEMPTS`  | no       | `3`                               | Max retry attempts for the async `process_test` Celery task before it's marked failed         |
| `IMAGEMAGICK_TIMEOUT_SECONDS`| no       | `60`                              | Per-command timeout for ImageMagick subprocesses                                              |
| `GUNICORN_WORKERS`\*         | no       | `3`                               | Number of gunicorn worker processes                                                           |
| `REDIS_URL`                  | no       | `redis://localhost:6379/0`        | Valkey/Redis broker URL. **Not set in `deploy/.env.example`** and not overridden by `deploy/docker-compose.yml` (the `api`/`worker` services only set `env_file: ../.env`) — following this doc's own setup steps leaves it at the `redis://localhost:6379/0` default, which is unreachable from inside a container. Add `REDIS_URL=redis://valkey:6379/0` to `.env` manually for Docker Compose to work                       |
| `CELERY_WORKER_CONCURRENCY`  | no       | `2`                               | Parallel ImageMagick pipelines per worker container                                           |
| `CELERY_TASK_ALWAYS_EAGER`   | no       | `False`                           | Celery/test tuning knob — runs tasks synchronously without a broker when `True` (used in tests) |
| `CELERY_TASK_EAGER_PROPAGATES`| no      | `False`                           | Celery/test tuning knob — re-raises task exceptions synchronously when eager                  |
| `CELERY_TASK_ACKS_LATE`      | no       | `True`                            | Celery tuning knob — ack tasks after execution rather than before                              |
| `CELERY_WORKER_PREFETCH_MULTIPLIER`| no | `1`                               | Celery tuning knob — number of tasks a worker prefetches per poll                              |
| `CELERY_TASK_REJECT_ON_WORKER_LOST`| no | `True`                           | Celery tuning knob — requeue a task if its worker process dies mid-execution                   |
| `API_UPSTREAM`               | no       | `http://api:8000`                 | SPA nginx's backend proxy target. Override when `spa` is the only publicly reachable container (e.g. Kubernetes) and `api` lives at a different address — see "Deploying with a separate public/private split" below. Read only by the `spa` container's nginx entrypoint — **not** part of the `.env`-driven config above; the `spa` service in `deploy/docker-compose.yml` has no `env_file`/`environment` block, so this must be set directly as a container env var on `spa` (e.g. via a docker-compose override's `environment:`) or as a pod env var in Kubernetes |
| `RESOLVER_ADDRESS`           | no       | `127.0.0.11`                      | DNS resolver nginx uses to re-resolve `API_UPSTREAM`'s hostname at request time. `127.0.0.11` is Docker Compose's embedded DNS; override to match the target platform's DNS server. Same caveat as `API_UPSTREAM`: set as a container/pod env var on `spa` specifically, not via `.env` |

\* `GUNICORN_WORKERS` is not a Django setting — it's read directly by the shell
entrypoint (`backend/scripts/start.sh`, `--workers "${GUNICORN_WORKERS:-3}"`)
rather than via `env.int()` in `settings.py` like the other variables in this
table.

When `AWS_IAM_AUTH_ENABLED=1`, Postgres, S3 and the broker are reached through IAM
rather than the credentials above, and a separate set of variables applies
(`REDIS_HOST`, `REDIS_IAM_USERNAME`, `REDIS_IAM_CACHE_NAME`, `DATABASE_HOST`, …) —
see [AWS IAM Authentication](aws-iam-auth.md).

---

## Production Deployment

### Checklist

- [ ] `DEBUG=0`
- [ ] `DJANGO_SECRET_KEY` set to a unique random value
- [ ] `ALLOWED_HOSTS` includes the production hostname
- [ ] `CSRF_TRUSTED_ORIGINS` — optional; leave empty for same-host HTTPS-terminating proxies (the backend already trusts the SPA nginx container's `X-Forwarded-Proto` header via `SECURE_PROXY_SSL_HEADER`). Only set it if the browser's origin differs from what Django sees, e.g. a split-host deployment
- [ ] Database backed up before `make migrate`
- [ ] S3 bucket exists and IAM credentials have `s3:PutObject`, `s3:GetObject`, `s3:DeleteObject`
- [ ] `S3_PUBLIC_BASE_URL` set only if the real S3 endpoint isn't already browser-reachable (typically unset in prod)

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

### Deploying with a separate public/private split (e.g. Kubernetes)

Some hosting platforms only expose one container/service publicly. If `api`
is deployed separately (e.g. its own Kubernetes Deployment behind a
`ClusterIP` Service) and only `spa` has a public Ingress, `spa`'s nginx must
be told where to find `api` and how to resolve it — Docker Compose's
embedded DNS (`127.0.0.11`) and service-name resolution (`api`) don't exist
outside Compose.

Set on the `spa` container/pod:

| Variable           | Example (Kubernetes)                              |
|--------------------|-----------------------------------------------------|
| `API_UPSTREAM`     | `http://api.<namespace>.svc.cluster.local:8000`    |
| `RESOLVER_ADDRESS` | `10.96.0.10` — a common default kube-dns/CoreDNS ClusterIP; use the actual ClusterIP of the cluster's `kube-dns`/`coredns` Service (`kubectl get svc -n kube-system kube-dns`), or the nameserver listed in `/etc/resolv.conf` inside a pod |

nginx's `resolver` directive resolves its argument **at config-parse time**
(container start / `nginx -s reload`) using the system resolver, and fails
hard (`[emerg] host not found in resolver`) if that lookup doesn't succeed.
Using a Service *hostname* like `kube-dns.kube-system.svc.cluster.local` here
reintroduces the boot-time DNS dependency this feature is meant to avoid — if
that name isn't resolvable yet when nginx starts, the container won't come
up. Prefer a bare IP address as shown above; a hostname is a riskier
secondary option and should only be used if the resolver's own address is
guaranteed to be resolvable before nginx starts.

docker-compose deployments need no changes: the Dockerfile's defaults
(`http://api:8000` / `127.0.0.11`) already match Compose's service name and
embedded DNS.

**Read-only root filesystems:** nginx's envsubst-on-templates entrypoint
renders `frontend/nginx.spa.conf.template` to
`/etc/nginx/conf.d/default.conf` at container start. Under
`readOnlyRootFilesystem: true` (a common Kubernetes Pod/container
`securityContext` hardening setting), this write fails silently — the
entrypoint still exits `0`, and nginx falls back to serving the base image's
stock `default.conf`, giving no SPA and no API proxying with no visible
error. If you set `readOnlyRootFilesystem: true` for the `spa` container,
either set it to `false` for this container specifically, or mount a
writable `emptyDir` volume at `/etc/nginx/conf.d` (and, if also templating
other paths, consider the base image's other writable directories such as
`/etc/nginx/templates`, `/var/cache/nginx`, and `/var/run`).

Kubernetes manifests (Deployment/Service/Ingress) themselves are managed
outside this repo.
