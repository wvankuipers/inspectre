---
name: inspectre-sync-docs
description: Use whenever a change alters architecture, API surface, routes, models, storage, or workflow — before finishing the task — to keep docs/ and CLAUDE.md from going stale.
---

# Sync docs after an architecture-affecting change

`docs/` is the source of truth for architecture detail; `.claude/CLAUDE.md` only holds
required-workflow rules and a pointer to `docs/README.md`. Update whichever owns the
area you changed:

| Changed area                          | File to update                    |
|----------------------------------------|-------------------------------------|
| Models (`core/models.py`, signals)     | `docs/data-model.md`               |
| API surface (`/api/*` or legacy)       | `docs/api.md`                      |
| Image diff pipeline / Celery task      | `docs/image-diffing.md`            |
| S3 layout, thumbnails, presigning      | `docs/storage-and-thumbnails.md`   |
| Frontend routes/components/conventions | `docs/ui.md`                       |
| Django admin                           | `docs/admin.md`                    |
| Infra, env vars, make targets, deploy  | `docs/deployment-and-config.md`    |
| AWS IAM auth                           | `docs/aws-iam-auth.md`             |
| Test suite structure/fixtures          | `docs/tests-and-fixtures.md`       |
| Notable architectural decision/tradeoff| `docs/decisions.md`                |

Steps:

1. Identify every `docs/*.md` file that describes the area you changed (a change can
   touch more than one — e.g. a new model field usually needs both `data-model.md` and
   `api.md`).
2. Update those files so they match the new code exactly (tables, code snippets, route
   lists) — treat stale docs as a bug.
3. Only touch `.claude/CLAUDE.md` if the *required workflow rules themselves* changed
   (new gate, new tool, new branch policy) — not for architecture detail, which belongs
   in `docs/` only. If you do edit it, re-run `wc -w .claude/CLAUDE.md` and keep it
   ≤200 words.
4. Do this in the same task/commit as the code change — don't defer it.
