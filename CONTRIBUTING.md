# Contributing to Inspectre

Thank you for your interest in contributing!

## Prerequisites

- Docker and Docker Compose
- GNU Make
- Git

## Development setup

1. Clone the repository and copy the example env file:

   ```bash
   git clone https://github.com/wvankuipers/inspectre.git
   cd inspectre
   cp .env.example .env
   ```

2. Start all services:

   ```bash
   make up
   ```

3. Run database migrations:

   ```bash
   make migrate
   ```

4. (Optional) Seed demo data:

   ```bash
   docker compose -f deploy/docker-compose.yml --env-file .env run --rm api python manage.py seed_demo
   ```

The SPA is available at `http://localhost:4200` and the API at `http://localhost:8000`.

## Running tests

```bash
make test            # all tests
make test-fast       # backend only, no ImageMagick
make test-slow       # backend including image diff tests
make test-frontend   # Angular/Vitest
```

## Linting

```bash
make lint        # check only
make lint-fix    # auto-fix
```

## Submitting changes

1. Fork the repository and create a branch from `main`.
2. Make your changes, including tests for any new behaviour.
3. Ensure all tests pass and linting is clean.
4. Open a pull request against `main` with a clear description of what changed and why.

For significant changes, open an issue first to discuss the approach.

## Code style

- Backend: [Ruff](https://docs.astral.sh/ruff/) with rules E, F, I, B, UP, DJ; 120-character line length.
- Frontend: Angular ESLint + Prettier.

Both are enforced by CI and auto-fixable via `make lint-fix`.
