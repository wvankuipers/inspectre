# Inspectre Documentation

This folder describes the **Inspectre** application — a Django + Angular 22 visual regression testing service. The legacy Rails codebase is in `legacy/` for reference only; the active codebase is the Django backend in `backend/` and the Angular frontend in `frontend/`.

## Reading order

1. [overview.md](overview.md) — what Inspectre is, domain concepts, end-to-end flow
2. [data-model.md](data-model.md) — Django models (`core/models.py`), signals, and apps
3. [api.md](api.md) — HTTP routes (legacy + SPA), DRF views and serializers
4. [image-diffing.md](image-diffing.md) — ImageMagick comparison pipeline and services
5. [ui.md](ui.md) — Angular SPA: routes, components, services, visual conventions
6. [admin.md](admin.md) — Django admin configuration and rename-warning behaviour
7. [storage-and-thumbnails.md](storage-and-thumbnails.md) — S3 storage layout and thumbnail pipeline
8. [deployment-and-config.md](deployment-and-config.md) — env vars, Docker Compose, nginx, Makefile
9. [tests-and-fixtures.md](tests-and-fixtures.md) — pytest packs: models, services, serializers, API, admin
10. [decisions.md](decisions.md) — architectural decisions, config knobs, fixed bugs, deferred gaps
