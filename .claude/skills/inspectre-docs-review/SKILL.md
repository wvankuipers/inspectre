---
name: inspectre-docs-review
description: Use to review documentation changes in this repo — `.claude/CLAUDE.md` and `docs/*.md` — for staleness, correct ownership, and consistency with the actual code.
---

# Inspectre documentation review

`.claude/CLAUDE.md` and `docs/` have a strict division of responsibility (see
`inspectre-sync-docs`): CLAUDE.md holds only required-workflow rules and a pointer;
`docs/` owns all architecture detail. Review against that split, not generic doc quality.

## Checklist

- **CLAUDE.md word budget** — must stay ≤200 words. Run `wc -w .claude/CLAUDE.md` and
  flag if it's over, or if it's crept back toward re-adding architecture detail
  (models/API/settings/routes tables) that belongs in `docs/` instead.
- **Correct doc owns the change** — cross-check the changed content against this
  ownership map; flag anything landing in the wrong file or landing in CLAUDE.md instead
  of `docs/`:
  | Area | File |
  |---|---|
  | Models/signals | `docs/data-model.md` |
  | API surface (`/api/*` or legacy) | `docs/api.md` |
  | Image diff pipeline/Celery task | `docs/image-diffing.md` |
  | S3 layout/thumbnails/presigning | `docs/storage-and-thumbnails.md` |
  | Frontend routes/components/conventions | `docs/ui.md` |
  | Django admin | `docs/admin.md` |
  | Infra/env vars/make targets/deploy | `docs/deployment-and-config.md` |
  | AWS IAM auth | `docs/aws-iam-auth.md` |
  | Test suite structure/fixtures | `docs/tests-and-fixtures.md` |
  | Architectural decisions/tradeoffs | `docs/decisions.md` |
- **Accuracy against code** — for any doc claiming a specific field name, endpoint path,
  env var, default value, or table/list of settings, spot-check it against the actual
  source (`core/models.py`, `core/serializers.py`, URL config, `settings.py`,
  `deploy/docker-compose.yml`) rather than trusting the prose. Stale docs (claiming
  something the code no longer does) are the primary failure mode to catch.
- **No duplication drift** — the same fact (e.g. a make target, an env var) shouldn't
  exist in two docs with different values — that's how staleness starts. If duplicated,
  flag which copy is now wrong or suggest consolidating to one owning file.
- **Legacy vs current is labeled** — several docs intentionally keep historical
  Rails/Dragonfly context (`data-model.md`, `storage-and-thumbnails.md`,
  `image-diffing.md`) alongside the current Django/S3 implementation. Flag if new content
  blurs "this is history" vs "this is current" — the reader must be able to tell which
  is real by looking at the current codebase.
- **Code examples compile/match** — TypeScript interfaces, Python snippets, and YAML/JSON
  fragments quoted in docs should match the real file's current shape, not an
  approximation.
- **`docs/README.md` index** — if a new `docs/*.md` file was added, confirm it's linked
  from `docs/README.md`'s reading order.

## Reporting

Verify each candidate finding against the actual current file/code before reporting —
don't flag something that was already accurate. Report via the `ReportFindings` tool,
most severe first.
