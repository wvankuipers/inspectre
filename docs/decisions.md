# Decisions

This started as an open-questions list (`open-questions.md`). All ten questions have now been answered; this doc records each decision and the reasoning, plus the security/quality fixes that come along for free in the rebuild.

The user opted for **"parity + flag obvious improvements"**. Below: parity choices, decided improvements, and the bugs the rebuild fixes by virtue of being a rewrite.

---

## Decisions

| # | Question                                            | Decision                                                                                            |
| - | --------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| 1 | Run retention per suite                             | **Keep 5 as default (parity)**, env-overridable via `RUN_RETENTION_PER_SUITE`.                      |
| 2 | Pass threshold                                      | **Keep 0.1% as default (parity)**, env-overridable via `IMAGE_DIFF_THRESHOLD`.                     |
| 3 | First-time baselining                               | **Manual approval + UI badge (superseded auto-baseline).** First run for a new key has nothing to compare against and does not pass automatically; a human must approve it via "Set as baseline" before it counts as passing or becomes the baseline. Originally decided as auto-self-baseline for frictionless CI ingest; reversed because nothing should become a trusted reference image without a human looking at it first. |
| 4 | Slug behaviour on rename                            | **Auto-update slug on rename.** Old deep-links break; old baselines get severed because the `key` changes. Document this clearly to admins. |
| 5 | S3 access mode                                      | **Public bucket.** URLs are stable, CDN-friendly. Matches "no auth" model.                          |
| 6 | Admin UI                                            | **Django Admin + single shared `is_staff` user.** Public API stays no-auth; only `/admin/` requires the shared login. |
| 7 | API versioning                                      | **Keep legacy URLs.** `POST /runs`, `POST /tests`, `PATCH /tests/:id`, `GET /baselines/:key` un-prefixed for CI client compatibility. SPA-internal routes can live under `/api/`. |
| 8 | Data migration                                      | **No migration.** Rebuild starts empty. Old install runs in parallel until decommissioned.          |
| 9 | Visual identity                                     | **Full redesign with Angular Material 3.** Drop Merriweather, deep-blue masthead, bouncing logo. Use Material 3 defaults. |
| 10| Legacy security fixes (shell-injection, exit codes) | **Not back-ported.** Legacy is decommissioned at cutover. Fix in the rebuild only.                  |

---

## Configuration knobs the rebuild exposes

Each of these is hardcoded in the Ruby code today. The rebuild exposes them as Django settings (env-var-overridable). Defaults match today's behaviour.

| Constant                | Today                                          | Setting                     | Default |
| ----------------------- | ---------------------------------------------- | --------------------------- | ------- |
| Pass threshold (%)      | `0.1` in `ScreenshotComparison#determine_pass` | `IMAGE_DIFF_THRESHOLD`      | `0.1`   |
| Runs retained per suite | `5` in `Suite#purge_old_runs`                  | `RUN_RETENTION_PER_SUITE`   | `5`     |
| Default fuzz level      | `30%` in `Test#default_values`                 | `DEFAULT_FUZZ_LEVEL`        | `30%`   |
| Default highlight colour| `ff0000` in `Test#default_values`              | `DEFAULT_HIGHLIGHT_COLOUR`  | `ff0000`|
| Thumbnail width         | `300` in `Thumbnail#create_thumbnail`          | `THUMBNAIL_WIDTH`           | `300`   |
| Thumbnail JPEG quality  | `90` in `Thumbnail#create_thumbnail`           | `THUMBNAIL_JPEG_QUALITY`    | `90`    |
| Canvas background       | `white` in `Canvas`                            | `CANVAS_BACKGROUND`         | `white` |

---

## Bugs/risks fixed by the rebuild

These are issues in the legacy code. They will not be back-ported (decision #10), but the rebuild must not reproduce them.

### Shell-injection on user-controlled fields (security)

Legacy `compare ... -fuzz #{fuzz_level} -highlight-color '##{highlight_colour}'` interpolates unauthenticated client input into a shell command. Submitting `fuzz_level: "30% ; rm -rf /"` would execute arbitrary shell commands.

**Rebuild fix**: strict input validation at the API boundary.
- `fuzz_level` must match `^\d+(\.\d+)?%$`
- `highlight_colour` must match `^[0-9a-fA-F]{6}$`
- `crop_area` must match `^\d+x\d+\+\d+\+\d+$`

Reject anything else with `400 Bad Request`. Even after validation, every interpolated path is `shlex.quote`d.

### Silent ImageMagick failures

Legacy doesn't check `convert`/`compare` exit codes; failures surface as nonsensical "0% difference / Fail" rows.

**Rebuild fix**: check return codes. `compare` returns 0 (identical) or 1 (different) — both fine. Anything else is an error → 500 with a structured log line.

### Race condition on baseline upsert

Two simultaneous `POST /tests` for the same key both see "no baseline", both upsert, last write wins.

**Rebuild fix**: `Baseline.objects.update_or_create(key=…)` inside `transaction.atomic` with `select_for_update()` on the matching row.

### Thumbnail cache staleness

Legacy thumbnails are keyed by `<key>_test_<id>_screenshot`. If the underlying screenshot changes, the cached thumbnail can drift.

**Rebuild fix**: thumbnails are written to S3 at the same time as the originals; no separate cache layer. If a screenshot is replaced, the thumbnail is replaced atomically.

### Hardcoded Dragonfly secret in source

Legacy has `secret "5fc2f8d1..."` literal in `config/initializers/dragonfly.rb`.

**Rebuild fix**: not reproduced. S3 URLs are either public (decision #5) or signed via the SDK using `S3_SECRET_ACCESS_KEY` from the environment.

### `/tests/new` creates DB rows on every render

Legacy view auto-creates project/suite/run on every page load. Side-effecting GET endpoint.

**Rebuild fix**: drop the dev-only `/tests/new` and `/runs/new` views entirely.

---

## Functional gaps left for later

These are not part of the v1 rebuild but worth noting:

- **Pagination/search** — projects/suites/runs/baselines are all `Model.all` style. Fine until you have lots of them. Add DRF pagination + Material `<mat-paginator>` when needed.
- **Audit log for "Set as baseline"** — no record of who/when. Without auth this is unattributed anyway. Revisit if/when auth is added.
- **Webhooks / notifications** — no run-complete webhook. CI consumers poll the `POST /tests` response or the run page.
- **Multi-baseline per key** — one baseline per (project, suite, name, browser, size) tuple. Use distinct `browser`/`size` values to discriminate platforms.
- **Per-suite/per-test thresholds** — global pass threshold and fuzz level only. Add `Suite.diff_threshold` and `Suite.default_fuzz_level` later if needed.
- **Ignore regions** — only inverse mode (`crop_area`) is supported. No "ignore this rectangle" support today; defer.

---

## Implications of the decisions

A few decisions interact in ways worth calling out:

**Decision #4 (auto-update slug) + Decision #3 (manual approval, superseding auto self-baseline) + the `key` formula** — renaming a project from "Acme" to "Acme Inc" changes every contained test's `key` (because `key` is `project.name` slugified). Every existing baseline becomes orphan; the next test for each key has nothing to compare against and no longer passes automatically — it's stored unbaselined, marked `is_new_baseline = true` and **not passed**, awaiting a human clicking "Set as baseline". The user will see "New baseline" badges on every test in the next run, now also marked as failing until approved — a smaller surprise than the old silent auto-pass, not a new one. **This is the intended behaviour given the decisions, but it surprises admins.** Document it on the admin rename screen and in `admin.md`.

If this turns out to be too painful in practice, the right fix is to decouple `key` from `name` (use stable `project_id`/`suite_id` in the key formula). That was offered as option D in question #4 and rejected; revisit only if rename pain is real.

**Decision #6 (Django Admin needs login) + Decision #5 (no auth on API)** — there are now *two* security postures in the same app: the API is open, the admin requires a login. Document the shared admin password somewhere safe (a secret manager, not the repo). Recommend rotating it after onboarding.

**Decision #9 (full Material redesign) + Decision #8 (no migration)** — there's no continuity story. Users at cutover see a brand-new app with empty data and no "old runs" to compare against. Communicate the cutover clearly; consider a banner during the first week pointing at the old install for reference.

**Decision #10 (no legacy back-port) + the shell-injection finding** — the legacy app is exploitable until it's turned off. **Treat the cutover as security-critical**: until the legacy install is decommissioned, anyone with network access can run arbitrary commands on it. Either firewall it off, take it down, or accept the risk for the cutover window.
