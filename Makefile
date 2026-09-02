# Inspectre — top-level developer commands. Run `make help` for the full list.

# ---- Variables ------------------------------------------------------------

COMPOSE          := docker compose -f deploy/docker-compose.yml --env-file .env
COMPOSE_DEV      := docker compose -f deploy/docker-compose.yml --env-file .env --profile dev
BACKEND_RUN      := $(COMPOSE) run --rm api
BACKEND_EXEC     := $(COMPOSE) exec api
DEV_RUN          := $(COMPOSE_DEV) run --rm api-dev   # api image + dev tooling
# Frontend prod image is nginx-only; dev runs go through a Node container.
FRONTEND_DEV     := $(COMPOSE_DEV) run --rm spa-dev
PYTEST           := pytest -n auto
PYTEST_FAST      := $(PYTEST) -m "not slow"
# Fast tests: no real ImageMagick. The race-condition class in test_models.py
# is marked @pytest.mark.slow and runs in test-slow.
PYTEST_FAST_PACKS := \
    core/tests/test_health.py \
    core/tests/test_serializers.py \
    core/tests/test_spa_api.py \
    core/tests/test_admin.py \
    core/tests/test_models.py \
    core/tests/test_settings.py \
    core/tests/test_tasks.py
# Slow tests: real `convert`/`compare` shell-outs.
PYTEST_SLOW_PACKS := \
    core/tests/test_legacy_api.py \
    core/tests/test_screenshot_comparison.py \
    core/tests/test_baseline_upsert.py \
    core/tests/test_seed_demo.py

.DEFAULT_GOAL := help
.PHONY: help up down restart logs shell-api shell-db migrate makemigrations \
        admin-user seed lint lint-fix test test-fast test-slow test-frontend \
        check-deps freeze build clean reset perf

# ---- Help -----------------------------------------------------------------

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---- Stack lifecycle ------------------------------------------------------

up: ## Start the full stack (api, spa, db, minio) in the background
	$(COMPOSE) up -d --wait
	@echo "API:   http://localhost:8000"
	@echo "SPA:   http://localhost:4200"
	@echo "MinIO: http://localhost:9001  (minio / miniominio)"

down: ## Stop and remove all containers (preserves volumes)
	$(COMPOSE) down

restart: down up ## Restart the full stack

logs: ## Tail logs from the api service
	$(COMPOSE) logs -f api

# ---- Shells ---------------------------------------------------------------

shell-api: ## Open a Django shell inside the api container
	$(BACKEND_EXEC) python manage.py shell

shell-db: ## Open a psql session against the dev database
	$(COMPOSE) exec db psql -U inspectre inspectre

# ---- Database -------------------------------------------------------------

migrate: ## Apply pending migrations
	$(BACKEND_EXEC) python manage.py migrate

makemigrations: ## Generate new migrations from model changes
	$(BACKEND_EXEC) python manage.py makemigrations

admin-user: ## Bootstrap the admin user (reads ADMIN_USERNAME / ADMIN_PASSWORD from env)
	$(BACKEND_EXEC) python manage.py ensure_admin_user

seed: ## Load demo data into a running stack (wipes any existing demo data first)
	$(BACKEND_EXEC) python manage.py seed_demo

# ---- Lint -----------------------------------------------------------------

lint: ## Lint backend (ruff) and frontend (angular-eslint).
	$(DEV_RUN) ruff check . && $(DEV_RUN) ruff format --check .
	$(FRONTEND_DEV) sh -c "npm ci --silent && npm run lint"

lint-fix: ## Auto-fix lint issues where possible.
	$(DEV_RUN) ruff check --fix .
	$(DEV_RUN) ruff format .
	$(FRONTEND_DEV) sh -c "npm ci --silent && npm run lint -- --fix"

# ---- Tests ----------------------------------------------------------------

test: test-fast test-slow test-frontend ## Run every test pack (cheap → expensive)

test-fast: ## Run the cheap test packs (~1s)
	$(DEV_RUN) $(PYTEST_FAST) $(PYTEST_FAST_PACKS)

test-slow: ## Run the expensive test packs (~5s) — needs ImageMagick
	$(DEV_RUN) $(PYTEST) $(PYTEST_SLOW_PACKS)

test-frontend: ## Run Angular unit tests (Vitest, headless by default)
	$(FRONTEND_DEV) sh -c "npm ci --silent && npm test -- --watch=false"

# ---- Dependencies ---------------------------------------------------------

check-deps: ## Verify requirements.txt is in sync with pyproject.toml
	$(DEV_RUN) sh -c "pip-compile --quiet -o /tmp/inspectre-deps.txt pyproject.toml && diff -q requirements.txt /tmp/inspectre-deps.txt"
	@echo "OK: requirements.txt is up to date"

freeze: ## Regenerate requirements.txt and requirements-dev.txt
	$(DEV_RUN) pip-compile --upgrade -o requirements.txt pyproject.toml
	$(DEV_RUN) pip-compile --upgrade --strip-extras --extra=dev -o requirements-dev.txt pyproject.toml

# ---- Build / clean --------------------------------------------------------

build: ## Build both Docker images locally (api + spa)
	$(COMPOSE) build

clean: ## Stop containers and remove volumes (DESTROYS local data)
	$(COMPOSE) down -v

# start.sh (the api entrypoint) runs migrate + ensure_admin_user itself, and
# `up --wait` blocks until api is healthy — i.e. until those have completed.
# So no separate migrate/admin-user step here (running one would race start.sh).
reset: clean build up ## Nuke everything and rebuild from scratch

# ---- Performance test -------------------------------------------------------

perf: ## Run the performance stress test against the local stack (override with ARGS)
	cd perf && python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt && .venv/bin/python run_perf.py $(ARGS)
