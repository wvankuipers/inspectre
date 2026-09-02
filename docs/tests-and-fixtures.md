# Tests & fixtures

This is a map of **what tests exist today** in `backend/core/tests/` and what each pack covers — not a spec written ahead of implementation. It was originally written as a pre-implementation plan describing a design (auto-self-baseline, synchronous `POST /tests`) that was superseded before ship; this revision was cross-checked directly against the current test files and the services/tasks they exercise, and describes the app as it actually behaves.

Two designs to know before reading any of the sections below:

- **Manual baseline approval.** A first-ever upload for a given `Test.key` has nothing to compare against. It is stored with `passed=False`, `original_passed=False`, no comparison images, and **no `Baseline` row is created**. A human must explicitly promote it via "Set as baseline" (`PATCH /tests/:id` with `test[baseline]=true`, or `POST /api/tests/<id>/set-baseline/`) before it counts as passing or becomes the comparison target for future submissions. There is no auto-self-baseline path anywhere in the current code.
- **Async processing.** `POST /tests` stages the upload to S3, creates a `Test` row with `status="pending"`, enqueues `core.tasks.process_test` via Celery, and returns immediately. The diff pipeline (crop → compare → thumbnails → persist) runs in the worker. Clients poll `GET /tests/:id/status` (legacy) or the SPA's bulk/detail endpoints for `status` to flip to `"done"`/`"failed"`.

## Historical context (legacy Ruby app — no longer applicable)

The original app (Rails + RSpec + Cucumber) had minimal test coverage; none of it was ported, and none of these files exist in this repo. Kept here only as background on what "legacy parity" comments elsewhere in the codebase refer to.

- RSpec (`spec/`) pinned: `ImageGeometry` width/height, `ImageProcessor.crop` returning true, `Canvas` max-of-two-dimensions sizing, an identical-pair-passes / different-size-fails screenshot comparison, and a "five consecutive failures" flag on `Test`. No controller specs, no request specs, no Baseline lifecycle spec beyond what the comparison spec exercised.
- Cucumber (`features/`) covered two end-to-end flows (projects listing, POST-then-view-run) via Capybara + Poltergeist/PhantomJS — dead upstream, doesn't run today.
- `bin/demo_test_run` was a manual smoke-test script hitting real URLs through the same dead PhantomJS toolchain.

None of this constrains the current Django/pytest suite; it's included only so a reader who encounters "legacy parity" in a code comment knows what it's referring to.

## Current test suite

### Layout

```text
backend/
└── core/tests/
    ├── conftest.py                       # shared fixtures — see below
    ├── fixtures/images/
    │   ├── testcard.jpg                  # 400x300
    │   ├── testcard_large.jpg            # 500x375
    │   ├── run1.png                      # intentional-diff pair, part A
    │   └── run2.png                      # intentional-diff pair, part B
    ├── test_screenshot_comparison.py     # diff pipeline (slow — real ImageMagick)
    ├── test_tasks.py                     # Celery task: locking, fencing, retries
    ├── test_baseline_upsert.py           # baseline_upsert error handling (slow)
    ├── test_serializers.py               # wire-format contracts
    ├── test_legacy_api.py                # un-prefixed CI-client endpoints
    ├── test_spa_api.py                   # /api/* endpoints
    ├── test_admin.py                     # auth, rename banner, processing-queue admin
    ├── test_models.py                    # slugs, key formula, signals, cascades
    ├── test_health.py                    # /healthz/
    ├── test_settings.py                  # settings.py-level behaviour
    ├── test_s3.py                        # presigned URLs, staging key helper
    ├── test_s3_iam_auth.py               # get_s3_client credential branching
    ├── test_iam_credential_provider.py   # ElastiCache IAM auth token signing
    ├── test_iam_postgres_backend.py      # RDS IAM auth DB backend
    └── test_seed_demo.py                 # seed_demo management command (slow)
```

Run with `cd backend && pytest`, or via `make test-fast` (no ImageMagick shell-outs) / `make test-slow` (includes real `convert`/`compare`). Tests are marked `@pytest.mark.slow` individually or at module scope (`pytestmark = [pytest.mark.django_db, pytest.mark.slow]`); `test-fast` runs with `-m "not slow"`.

### Shared fixtures — `core/tests/conftest.py`

Model factories (`factory_boy`) for `Project`, `Suite`, `Run`, `Test`, exposed as `project_factory`, `suite_factory`, `run_factory`, `test_factory`. `Baseline` doesn't fit factory_boy cleanly (no defaults that produce a unique `key`), so it gets a plain function fixture, `baseline_factory(**kwargs)`, that fills in sensible defaults and lets a test override anything (`suite`, `name`, `browser`, `size`, `key`, `test`, …).

Image fixtures: `testcard`, `testcard_large`, `run1`, `run2` — each a `pathlib.Path` fixture pointing at `fixtures/images/`. `upload(path)` wraps one of those paths as a `SimpleUploadedFile`-like object for feeding into `ScreenshotComparison` directly (bypassing the view layer).

Two autouse fixtures keep the suite hermetic:

- `_filesystem_storage(settings, tmp_path)` — swaps `settings.STORAGES` to `FileSystemStorage` pointed at a per-test `tmp_path`, so no test needs a real S3/MinIO bucket. Tests that need real S3 semantics (IAM auth, presigning behaviour) mock at the `boto3` boundary directly instead.
- `_clear_presign_client_cache()` — `get_presign_s3_client` is `lru_cache`'d for performance; since the `settings` fixture mutates and reverts settings per test, a cached client from one test could otherwise leak a stale endpoint/region into the next. Clears the cache before and after every test.

## `test_screenshot_comparison.py` — the diff pipeline

`ScreenshotComparison(test, uploaded_file).run()` is the highest-leverage thing to test: it owns cropping, canvas padding, the ImageMagick `compare` shell-out, thumbnail rendering, and the manual-approval-vs-real-comparison branch. `run()` returns `True` when there was nothing to compare against (first upload or orphaned baseline) and `False` otherwise.

### What this pack covers

- **First upload requires manual approval** — `test_first_upload_requires_manual_approval`: `run()` returns `True`, `test.passed` and `test.original_passed` are both `False`, `diff == 0`, no comparison images, and critically `not Baseline.objects.filter(key=test.key).exists()`. This is the test that pins the superseded-design correction: nothing self-baselines.
- **Approval flow** — `test_approving_a_first_upload_establishes_the_baseline` promotes via `_set_as_baseline` and checks the `Baseline` row now exists and points at the test. `test_set_as_baseline_does_not_mutate_original_passed` guards that promotion flips `passed` but never touches the immutable `original_passed`.
- **Real comparisons once a baseline exists**: `test_identical_to_baseline_passes`, `test_different_image_fails` (via the `run1`/`run2` intentional-diff fixture pair), each preceded by a helper `_approve()` that simulates a human click.
- **Canvas padding** — `test_different_dimensions_pads_to_larger_canvas`: 400×300 vs 500×375 pads both to 500×375.
- **Crop** — `test_crop_area_uses_cropped_region`: `crop_area="200x150+0+0"` crops before comparison.
- **ImageMagick failure modes**: corrupt input raises `ImageDiffError` (`test_corrupt_input_raises_imagediff_error`); a timeout during `_crop_in_place` raises `ImageDiffError` with "timed out" (`test_imagemagick_timeout_raises_imagediff_error`, achieved by patching `subprocess.run` to raise `TimeoutExpired` on the first call).
- **Orphan cleanup on first-upload failure**: `test_first_upload_thumbnail_failure_leaves_no_orphaned_screenshot` proves the thumbnail is rendered *before* any storage write, so a thumbnail failure leaves nothing orphaned; `test_first_upload_second_save_failure_cleans_up_first_stored_file` proves that if the screenshot save succeeds but the thumbnail save then fails, the already-stored screenshot is deleted rather than left unreferenced.
- **Orphaned baseline file** — `test_orphan_baseline_requires_manual_reapproval`: `Baseline` row exists but its screenshot file is missing from storage → treated like a first upload (logs a warning, no comparison, not passed); the stale row is left as-is until a fresh approval fixes it.
- **Thumbnails** (per-field, pass/fail/first-upload matrix): `test_passing_run_populates_all_test_thumbnails`, `test_first_upload_only_populates_screenshot_thumbnail`, `test_failing_run_still_populates_test_thumbnails`, `test_baseline_thumbnail_attached_on_pass`, `test_thumbnail_width_matches_setting` (honours `settings.THUMBNAIL_WIDTH`).
- **Configurable threshold** — `test_pass_threshold_is_configurable`: `settings.IMAGE_DIFF_THRESHOLD` changes pass/fail without a code change.

### What it doesn't cover

- The `POST /tests` view layer (multipart parsing, field validation, response shape) — `test_legacy_api.py`.
- The Celery task wrapper around this service (locking, fencing, retries, S3 staging/download) — `test_tasks.py`.
- Serializer wire-format regressions — `test_serializers.py`.
- Shell-injection rejection at the validator boundary — also `test_legacy_api.py` (`TestValidateTestParams` and the parametrized `test_invalid_input_rejected_at_view`), since the validator runs before any `Test` row or shell command exists, not inside this service.

### Speed

Module-level `pytestmark = [pytest.mark.django_db, pytest.mark.slow]` — every test spawns real `convert`/`compare` subprocesses. Runs under `make test-slow`.

## `test_tasks.py` — Celery task correctness (locking, fencing, retries)

`core.tasks.process_test` is the async worker entry point, and it carries real correctness machinery documented at length in its own docstring: a Postgres session advisory lock keyed on `test_id` (guards against two invocations of the *same* test racing each other), a `processing_claim` fencing token (guards against a stale invocation completing sequentially after a newer one has already superseded it), a terminal-status check (guards against a duplicate message redelivery re-running a pipeline that already finished), and a `process_attempts` cap enforced *before* the risky pipeline work runs (so a crash mid-pipeline doesn't lose the attempt count). This is the single most heavily-tested file in the suite by scenario count, and deliberately so — this is where a subtle bug means either silently losing a screenshot's result or double-processing and corrupting a good one.

### What this pack covers

`TestProcessTestTask` (all under `pytestmark = pytest.mark.django_db`, most using `CELERY_TASK_ALWAYS_EAGER = True` for synchronous execution):

- **Happy path**: sets `status=DONE`, increments `process_attempts`, sets `is_new_baseline` from the comparison's return value, transitions through `STATUS_PROCESSING` before `STATUS_DONE` (`test_transitions_through_processing_before_done`), releases the advisory lock afterward (`test_releases_lock_after_successful_run` — checked by having the *same* connection call `pg_advisory_unlock` directly and asserting it returns `False`, since `pg_try_advisory_lock` is re-entrant within a session and wouldn't distinguish "released" from "never leaked").
- **`process_attempts` cap**: attempting exactly at the cap still processes normally (`test_attempt_at_cap_still_processes_normally`); attempting *over* the cap bails straight to `STATUS_FAILED` without touching `ScreenshotComparison` or downloading anything, but still deletes the staged upload and releases the lock (`test_attempt_over_cap_bails_to_failed_without_reprocessing`, `test_releases_lock_when_bailing_over_cap`).
- **Failure path**: an exception from `ScreenshotComparison.run()` sets `STATUS_FAILED`, the attempt counter still survives (it was committed before the pipeline ran), and the lock is still released.
- **Fencing token (`processing_claim`)**: a stale claim is rejected without touching status, attempts, or deletion (`test_stale_claim_is_rejected_without_touching_anything`); a matching claim proceeds normally; the lock is still released on a stale-claim bail.
- **Duplicate terminal delivery**: a redelivered message for a test already at `STATUS_DONE` or `STATUS_FAILED` is rejected without touching anything (two tests, one per terminal status), but a redelivery while still `STATUS_PROCESSING` (a genuine crash-retry, not a duplicate) proceeds normally and bumps attempts (`test_crash_retry_from_processing_status_still_proceeds_normally`).
- **Lock contention and requeueing** — the most involved tests in the file: a second thread holds the advisory lock via its own DB connection (a genuine separate Postgres session, unlike calling from the same session which would just re-acquire re-entrantly) to simulate a real concurrent invocation. `test_held_lock_blocks_concurrent_invocation_and_requeues` proves a contended call touches nothing and requeues itself via `apply_async` with an incremented `lock_wait_attempts`; `test_lock_contention_gives_up_after_cap` proves it stops requeueing at `_MAX_LOCK_WAIT_REQUEUES`; `test_requeued_invocation_eventually_completes_after_lock_clears` proves the requeue isn't just fire-and-forget — once the lock actually clears, the requeued call goes on to reach `STATUS_DONE`.
- **Mid-flight supersession** — `test_mid_flight_supersede_discards_stale_result_without_writing_or_deleting` (`@pytest.mark.django_db(transaction=True)`, since it runs the pipeline on a background thread's own DB session): a background task is paused mid-pipeline via a mocked `ScreenshotComparison.run()` that blocks on an event; while it's blocked, the test bumps `processing_claim` directly (simulating a concurrent admin restart). When the pipeline resumes and finishes, the task must re-check the claim after `refresh_from_db()` and discard its own result — never writing `STATUS_DONE`, never deleting the staged file the newer attempt still needs.

`TestDeleteTestFileKeysTask` — the batched S3 cleanup task fired from `Test`'s `pre_delete` signal: no-ops on an empty key list, batches every key into one `delete_objects` call, and logs-but-doesn't-raise on partial S3 errors, `ClientError`, or `EndpointConnectionError`.

### What it doesn't cover

- Correctness of the diff pipeline itself once it's invoked — `test_screenshot_comparison.py` (this file mocks `ScreenshotComparison` entirely).
- The view-layer enqueue call (`process_test.delay(...)` from `POST /tests`) — `test_legacy_api.py`'s `TestTestsCreateAsync` and the end-to-end `TestAsyncTestProcessingIntegration`.
- The admin-triggered restart/discard actions that bump `processing_claim` and re-enqueue — `test_admin.py`'s `TestRestartProcessingAction`/`TestDiscardFromQueueAction` (this file only proves `process_test` reacts correctly to a claim bump, not that the admin action produces one correctly).

### Speed

No `slow` marker — everything here mocks `ScreenshotComparison`, `_download_staged_file`, and `_delete_staged_file`, so there's no real ImageMagick or S3 I/O. The lock-contention tests spin up a real second thread with its own Postgres connection, so they do exercise real advisory-lock semantics; still fast in practice (sub-second per test).

## `test_baseline_upsert.py` — baseline upsert edge cases

Two focused, slow-marked regression tests for `core.services.baseline_upsert.upsert_baseline_from_test`:

- `test_long_test_key_does_not_truncate_baseline_file_paths` — a `Test.key` long enough (over 100 chars, under the OS path-component limit) that `baselines/<key>/screenshot.png` and `baselines/<key>/thumb-300.jpg` exceed `FileField`'s old `max_length=100`, which used to raise `SuspiciousFileOperation` when the storage backend tried to truncate a unique filename. Regression test for that bug — proves both paths are stored under the full, untruncated key.
- `test_storage_write_error_propagates_and_logs` — if the S3 write inside the upsert raises, the exception must propagate to the caller (not be swallowed) and `logger.exception` must fire with `"baseline upsert failed"` so operators have visibility.

### Speed

`pytestmark = [pytest.mark.django_db, pytest.mark.slow]` — both tests drive a real `ScreenshotComparison.run()` first to get a screenshot attached.

## `core/serializers.py` test pack — `test_serializers.py`

The serializers are the wire-format contract. Legacy CI clients expect the `LegacyRunSerializer`/`LegacyTestSerializer`/`LegacyBaselineSerializer` shapes exactly; the SPA serializers (`TestRowSerializer`, `RunSummarySerializer`, `RunDetailSerializer`, `SuiteDetailSerializer`, `ProjectSerializer`, `BaselineSerializer`, `TestHistoryEntrySerializer`) are free to evolve but still need their own regression coverage — especially the query-count-batching helpers (`build_run_counts`) that keep list endpoints from becoming N+1.

### What this pack covers

- **The single most important assertion in the file** — `test_legacy_test_serializer_uses_pass_not_passed`: the wire key is `"pass"`, never `"passed"` or `"pass_field"` (the intermediate DRF field name before `to_representation` renames it). Breaking this breaks every CI pipeline using the legacy API.
- **Frozen field sets** for `LegacyRunSerializer`, `LegacyTestSerializer` (parametrized), and `LegacyBaselineSerializer` — adding a model field must not silently leak into a legacy response.
- **URL shape survives renames** — `test_legacy_run_url_uses_current_slug_after_rename` (the URL follows the *current* project slug, not the slug at run-creation time) and `test_legacy_test_url_includes_anchor`.
- **`status` field presence** on both the legacy and SPA test-row serializers (`test_legacy_test_serializer_includes_status`, `test_spa_test_row_serializer_includes_status`) — both assert the freshly-created test's status is `"pending"`, pinning the async design.
- **Presigned URLs, not raw storage paths**, for every file field on both the legacy and SPA sides, and `None` (not `/` or a broken path) when the field is empty — `test_legacy_test_serializer_uid_fields_are_none_when_no_file` / `_are_presigned`, `test_spa_test_row_url_fields_are_none_when_no_file` (parametrized over all six SPA URL fields), `test_spa_test_row_screenshot_url_is_presigned`, `test_legacy_baseline_serializer_screenshot_url_is_presigned`.
- **`build_run_counts`** — the batching helper behind every list endpoint's passing/failing/unbaselined counts: correct per-run counts, runs with zero tests still present (not sparse), empty-input short-circuit with zero queries.
- **`RunSummarySerializer`** query-count discipline: `test_run_summary_serializer_uses_one_test_query_per_run` (`django_assert_num_queries(2)`), plus the specific regression guard `test_run_summary_unbaselined_reads_empty_baselined_keys_set_from_context_without_extra_query` — a legitimately empty `baselined_keys` set (a suite with zero baselines) must be read as-is from context, not treated as falsy and trigger a redundant fallback query. This distinction (`is None` vs. truthiness) is exactly the kind of one-character regression that's easy to reintroduce.
- **`TestHistoryEntrySerializer` / `serialize_test_history`** — the cross-run history endpoint's payload: exposes the immutable `original_passed`, never the mutable `passed` (`test_test_history_entry_serializer_uses_original_passed_not_passed`); includes run metadata (`run_id`, `run_sequential_id`, `run_created_at`); `serialize_test_history` returns key/name/browser/size/project_name/suite_slug plus runs ordered as given (newest-first, by convention of the caller).
- **`SuiteDetailSerializer`/`RunDetailSerializer`/`ProjectSerializer`** basics — 5-run cap surfaced, `project_name` denormalization, `ProjectSerializer` flattening suites and returning `null` (not an error) for a suite with no runs.
- **SPA wire format uses `passed`, never `pass`** — the mirror-image regression guard of the legacy `"pass"` test.

### What it doesn't cover

- Inbound deserialization on the legacy endpoints (multipart parsing, `FormParser` quirks) — `test_legacy_api.py`.
- The diff pipeline itself — `test_screenshot_comparison.py`.
- The Celery task wrapping around the pipeline — `test_tasks.py`.

### Speed

Pure DB + Python serialization, no ImageMagick, no S3, no threads. Runs in well under a second.

## `test_legacy_api.py` — end-to-end legacy view tests

Exercises the un-prefixed legacy endpoints (`POST /runs`, `POST /tests`, `PATCH /tests/:id`, `GET /baselines/:key.png`/`.json`, `GET /tests/:id/status`) the way CI clients actually use them: form-encoded or multipart, no auth, no CSRF. `POST /tests` is async: it stages the upload to S3 and enqueues `process_test`, returning `status="pending"` immediately — most tests here mock `core.views.legacy.process_test` and `_stage_upload_to_s3` so they exercise the view in isolation from Celery and S3.

### What this pack covers

- **`POST /runs`** (`TestRunsCreate`): find-or-create project+suite, per-suite `sequential_id` increments independently per suite, anonymous/no-CSRF acceptance, and 400s with the specific missing-field name for missing/empty `project`/`suite`.
- **`POST /tests` (async)** (`TestTestsCreate`, `TestTestsCreateAsync`): returns `status="pending"` immediately with `pass=False` and `is_new_baseline=None`; creates the `Test` row and calls `process_test.delay(test_id, staging_key, 0)` with the initial fencing-token value of `0`; 404 on an unknown `run_id`; 400 on a missing screenshot or missing required field.
- **Validation at the view boundary before any shell command runs** — `test_invalid_input_rejected_at_view`, parametrized over shell-injection payloads (`fuzz_level`, `highlight_colour`, `crop_area` each carrying a `touch {canary}` attempt) and malformed values (non-percent fuzz, wrong-length hex colour, malformed crop geometry). Each case asserts the 400 response, that the canary file was never created, and that no `Test` row was left behind. `TestValidateTestParams` unit-tests `validate_test_params` directly with non-string types and over-100% fuzz values.
- **`PATCH /tests/:id`** (`TestTestsPatchSetBaseline`): promotes via `test[baseline]=true` (wire response still uses `"pass"`), no-ops without the param, 404 on unknown id, and two transactional-integrity regressions: `test_failed_upsert_rolls_back_passed_flag` (a failing `upsert_baseline_row` must not leave `test.passed=True` with no matching `Baseline` — proves the promotion is wrapped in `transaction.atomic()`) and `test_failed_thumbnail_does_not_roll_back_promotion` (a thumbnail-render failure afterward is a side-effect failure, not an atomic-invariant failure — the promotion must survive it).
- **`GET /baselines/:key.png` / `.json`** (`TestBaselineLookup`): streams image bytes / returns metadata, 404 for both suffixes on an unknown key.
- **`GET /tests/:id/status`** (`TestTestsDetail`): the async polling endpoint — returns the current row, 404 on unknown id, includes `is_new_baseline` once `status="done"`.
- **Concurrency** (`TestConcurrentRunCreation`, skipped on SQLite where `select_for_update` is a no-op): five real threads POSTing `/runs` against the same suite produce six distinct, contiguous `sequential_id`s.
- **Full async integration** (`TestAsyncTestProcessingIntegration`, `@pytest.mark.slow`): POST with S3 staging mocked but Celery running eagerly and `ScreenshotComparison` running for real (against the hermetic `FileSystemStorage`) — proves the post-then-poll round trip actually reaches `status="done"` with a real diff result, and that the first submission for a new key reports `is_new_baseline=True`, `pass=False` (manual-approval design, not auto-pass).

### What it doesn't cover

- The SPA-only endpoints — `test_spa_api.py`.
- Image diff correctness in isolation — `test_screenshot_comparison.py`.
- The Celery task's own locking/fencing/retry semantics — `test_tasks.py` (this file proves the view *enqueues* correctly, not that the task processes correctly under contention).
- Wire-format field-set drift — `test_serializers.py`.

### Speed

Mostly fast (S3 and Celery mocked at the boundary). `TestAsyncTestProcessingIntegration` and `TestConcurrentRunCreation.test_no_collision_under_threads` are `@pytest.mark.slow` — real ImageMagick / real threads.

## `test_spa_api.py` — SPA-internal endpoints

Mirror of `test_legacy_api.py` for the `/api/` surface: JSON in, JSON out, no multipart. The contract here is internal — SPA and API ship from the same repo, so a contract change is a single PR touching both sides.

### What this pack covers

- **`GET /api/projects/`** (`TestProjectsList`): alphabetical sort, each project's suites inline, latest-run summary per suite, `null` latest_run for a suite with no runs, empty array for zero projects. Three query-count regression tests (`django_assert_num_queries`) prove the endpoint's total query count is constant per project regardless of suite count — pinning the `build_run_counts` batching fix and the `baselined_keys` context-passing fix that previously caused an N+1.
- **`GET /api/projects/<slug>/suites/<slug>/`** (`TestSuiteDetail`): 5-run cap, rename-changes-the-resolvable-slug (old slug 404s, new slug works), 404 for unknown project/suite, and a query-count-doesn't-scale-with-run-count regression test.
- **`GET /api/projects/<slug>/suites/<slug>/runs/<seq>/`** (`TestRunDetail`): inline tests, `passed` (never `pass`) in the wire format, 404 for unknown sequence id, `has_baseline` resolving correctly per test through this endpoint specifically (not just the bulk endpoint), and a regression test for a falsy-empty-set N+1 bug in `has_baseline` resolution.
- **`GET /api/projects/<slug>/suites/<slug>/tests/<key>/`** (`TestTestHistory`) — the cross-run history endpoint: newest-run-first ordering, per-entry `original_passed`/`is_new_baseline`/`status`, scoping so a same-named test in a different suite/project never leaks into another suite's history even if the raw key text would otherwise collide, and `test_promoted_test_still_reports_original_passed_false` — a promoted (passed=True) test's history entry still reports the immutable `original_passed=False`.
- **`POST /api/tests/<id>/set-baseline/`** (`TestSetBaselineSpa`): promotes to `passed=True`, returns `204` with an empty body, ignores request body content (can't be used to un-promote), 404 on unknown id, idempotent on an already-passed test.
- **`POST /api/tests/bulk/`** (`TestTestsBulk`) — the polling endpoint the SPA uses to refresh a set of test rows by id: returns only the requested ids, silently omits unknown ids, `passed` (not `pass`) in the wire format, empty-array short-circuits for empty/all-invalid/non-list/non-dict input, non-integer/`None`/boolean ids filtered out silently, duplicate ids deduplicated, and the id-count cap (`MAX_BULK_TEST_IDS`, monkeypatched down in the cap test to keep the test cheap). Also covers the same `is_baseline_source`/`has_baseline` supersession semantics as the run-detail endpoint, independently resolved per suite when the requested ids span two suites.
- **`GET /api/baselines/<key>/`** (`TestBaselineDetailSpa`): metadata + presigned screenshot URL, 404 on unknown key.

### What it doesn't cover

- The diff pipeline itself — `test_screenshot_comparison.py`.
- The Celery task — `test_tasks.py`.
- CORS. There is no `TestCors` class in the current test file — an earlier draft of this pack (and of this doc) described one, but no CORS behaviour exists in the current view/middleware stack to test; this section is fictional relative to the shipped app and has been dropped.

### Speed

Pure DB + DRF. Whole file runs in a couple of seconds — no ImageMagick, no threads.

## `test_admin.py` — admin auth, rename warning, and the processing-queue admin

The admin is the only authenticated surface in the app. Beyond the original auth-gate and rename-warning coverage, it now also covers the **processing queue admin** — a read-only `ProcessingQueueTest` proxy model plus two custom actions (`restart_processing`, `discard_from_queue`) for manually recovering or discarding stuck pending/processing rows, most commonly after a worker crash or a stuck S3/ImageMagick call.

### What this pack covers

- **Auth gate** (`TestAdminAuth`): anonymous → 302 to login; staff → 200; non-staff (logged in but `is_staff=False`) → 302, same as anonymous; `/api/` and the legacy endpoints stay anonymous — the gate must not extend there.
- **CRUD reachability** (`TestAdminCrud`): parametrized changelist-loads smoke test across `core/project`, `core/suite`, `core/run`, `core/test`, `core/baseline`, and `core/processingqueuetest`; add-page-loads for `core/project`/`core/suite` only (Run/Test/Baseline aren't realistically hand-created from the admin); `TestAdmin.diff_pct`'s custom formatted-percent column renders without crashing.
- **Rename-warning banner** (`TestRenameWarning`): visible on Project/Suite change forms, absent on their add forms, absent on Run/Test/Baseline change forms (they don't inherit `RenameWarningMixin`).
- **`ensure_admin_user`** (`TestEnsureAdminUser`): create-when-missing, password-rotation, no-rehash-on-unchanged-password (verified by hash equality, since Django's hashers salt every call), reconcile-`is_staff`-after-manual-clear, loud no-op when `ADMIN_PASSWORD` is unset, changing `ADMIN_USERNAME` creates a *second* admin rather than renaming the first, idempotent across 10 repeated runs.
- **`TestProcessingQueueAdmin`** — the read-only listing: only `pending`/`processing` tests are listed (not `done`/`failed`); no "Add" link and a 403 on the `/add/` URL directly (`has_add_permission=False`); the change page renders but has no Save button and no delete link (`has_change_permission=False` still allows *viewing* because Django checks the view-or-change permission string, and a superuser satisfies any permission check); the custom `waiting_since` column renders; and a query-count-doesn't-scale-with-row-count regression test pinning `list_select_related` against the N+1 that `run_label` (which walks run→suite→project per row) would otherwise cause.
- **`TestRestartProcessingAction`** — exercised through the real admin action POST endpoint (not by calling the method directly), which also proves the action runs despite this ModelAdmin's `has_change_permission` returning False (Django gates actions by their own `allowed_permissions`, not `has_change_permission`): restarts a test when its staged S3 upload is still present (`head_object` succeeds), bumps `processing_claim` as a genuinely new logical attempt (so `process_test` can reject a stale delivery from a prior click or crash-redelivery), reports (without restarting) when the staged upload is missing (S3 404), re-raises loudly on a non-404 `ClientError` (a 403/500 must not be reported as a harmless "missing upload"), and shows a "No queued tests to restart" message rather than a silent no-op when the selection's queryset ends up empty by action time.
- **`TestDiscardFromQueueAction`** — two-step confirmation like Django's built-in "Delete selected": unconfirmed request shows a confirmation page (with a cancel link) and deletes nothing; confirmed request deletes the row(s) and their staged S3 upload (`delete_object`, one call per row); a 404 from S3 (upload already gone) is not an error and the row is still deleted; a non-404 `ClientError` is not swallowed — it must propagate rather than silently leave the DB row deleted while its S3 object leaks.

### What it doesn't cover

- The login form itself — Django's stock view.
- Rate limiting / brute-force protection — not implemented.
- `manage.py changepassword` — operational, not behavioural.

### Speed

Pure DB, with S3 mocked at the `get_s3_client` boundary in the processing-queue tests. Whole file runs in a couple of seconds.

## `test_models.py` — model invariants and signals

Pins model-layer behaviour that isn't visible from any API surface: slug auto-update, the `Test.key` formula, per-suite sequential IDs, the run-purge signal, cascade declarations, and — since the async rework — the `status`/`is_new_baseline` fields and the pre_delete signal that enqueues async S3 cleanup instead of deleting files synchronously in the request.

### What this pack covers

- **Slug auto-update** (`TestSlugAutoUpdate`): set-from-name on create and on rename for both Project and Suite; Suite slug uniqueness is scoped per-project (two suites in different projects can share a slug; two in the same project cannot — `IntegrityError`); Project slug is globally unique even across names that slugify identically ("Acme Inc" vs "Acme  Inc").
- **`Test.key` formula** (`TestKeyFormula`): combines all five inputs (project, suite, name, browser, size); recomputes on re-save after a rename; a parametrized block covering whitespace/punctuation/Unicode folding (e.g. `"Café"` → `cafe-...`, `"Page/X"` → `...-pagex-...`).
- **`Run.sequential_id`** (`TestRunSequentialId`): starts at 1, increments per suite, independent per-suite counters, monotonic — doesn't resequence after a delete (deleting run #1 leaves the next run at #3, not #2). `TestRunSequentialIdRace` (skipped on SQLite, `@pytest.mark.slow`) proves five concurrent inserts under `select_for_update` never collide.
- **`purge_old_runs` signal** (`TestPurgeOldRuns`): keeps `RUN_RETENTION_PER_SUITE` most recent runs, cascades to Tests, doesn't cross suite boundaries, only fires on create (not on update), and — the async-era addition — `test_purge_deletes_test_files_from_storage`: purged Tests' S3 keys are sent to the `delete_test_file_keys` Celery task (via `transaction.on_commit`, executed inline in the test with `django_capture_on_commit_callbacks(execute=True)`), asserted by checking the mocked S3 client's `delete_objects` call rather than `storage.exists()` — the task now deletes via a raw boto3 client, bypassing Django's storage API and the hermetic `FileSystemStorage` swap entirely.
- **`TestDeleteTestFilesSignal`** — the `pre_delete` signal on `Test` itself: enqueues `delete_test_file_keys` with only the non-empty field keys (not empty-string placeholders for unattached fields); does not enqueue at all when no files are attached; and — the transactional-safety test — the task must not fire until the surrounding transaction actually commits (asserted mid-transaction, then after commit, then again with an explicit rollback to prove a rolled-back delete never enqueues anything).
- **Cascades** (`TestCascades`): deleting a Project wipes Suites/Runs/Tests; deleting a Suite wipes Baselines; deleting a Test does *not* delete its Baseline (`on_delete=SET_NULL` — the screenshot is still a valid baseline even if the originating Test row is gone).
- **`TestTestStatusField`**: a new Test defaults to `status="pending"`; an invalid status string fails `full_clean()` (`ValidationError`); `is_new_baseline` defaults to `None` and can be set to `True`; and `test_test_status_has_composite_index_with_created_at` — a direct introspection of `Test._meta.indexes` proving the `(status, created_at)` composite index exists, since `ProcessingQueueAdmin` filters on `status` and orders by `created_at` and needs both columns covered by one index to avoid a full table scan as the table grows.

### What it doesn't cover

- File handling on cascade delete beyond the explicit S3-cleanup-task assertions above — anything Django's own `FileField` machinery does natively.
- Default values for `fuzz_level`/`highlight_colour` — field defaults, not behaviour worth testing independently of the framework.
- The `next_run_seq` column directly — fully observed via `sequential_id`; asserting on the internal counter would couple the test to the implementation.

### Speed

Pure DB. `TestRunSequentialIdRace` is the one `@pytest.mark.slow` case — real threads, real Postgres locking, skipped entirely on SQLite.

## `test_health.py` — `/healthz/`

One test: `test_healthz_returns_200` — asserts a 200 with body `{"status": "ok"}` and, via `django_assert_num_queries(0)`, that the endpoint makes **zero database queries**. That's the whole point of a liveness/readiness probe: it must answer instantly even if the database is unreachable, so a DB outage doesn't also take down Kubernetes's judgment of whether the pod is alive.

## `test_settings.py` — settings-level behaviour

Small, focused tests for behaviour that lives in `settings.py` rather than in a service or view:

- `test_is_secure_reflects_forwarded_proto_header` / `_false_without_forwarded_proto_header` — proves `request.is_secure()` correctly reads `X-Forwarded-Proto` (needed behind a reverse proxy that terminates TLS).
- `test_csrf_trusted_origins_defaults_to_empty` — pins the default.
- `test_celery_task_acks_late_default` / `test_celery_worker_prefetch_multiplier_default` — pin `CELERY_TASK_ACKS_LATE=True` and `CELERY_WORKER_PREFETCH_MULTIPLIER=1` as the reliability-oriented defaults that `test_tasks.py`'s "redelivery" scenarios assume are in effect in production (acks-late is precisely the mechanism that makes the duplicate-delivery guards in `process_test` necessary in the first place).

## S3 / IAM / infra test files

Shorter, more mechanical packs — each pins one narrow piece of infrastructure glue rather than application behaviour.

- **`test_s3.py`** — `staging_key_for_test(id)` produces the expected `screenshots/staging/<id>/upload.png` path; `generate_presigned_url` returns `None` for an empty/`None` key, delegates to the cached presign client with the right bucket/key/expiry (default and custom `expires_in`), and — the one test that doesn't mock boto3 — `test_generate_presigned_url_produces_sigv4_url` signs a real presigned URL with dummy credentials and inspects the query string for `X-Amz-Signature` / `AWS4-HMAC-SHA256`, which would have caught botocore defaulting to SigV2 presigning in some regions.
- **`test_s3_iam_auth.py`** — `get_s3_client()` passes static `aws_access_key_id`/`aws_secret_access_key` when `AWS_IAM_AUTH_ENABLED=False`, and omits them entirely (letting boto3 fall through to the instance/task IAM role) when `True`.
- **`test_iam_credential_provider.py`** — `IAMElastiCacheCredentialProvider.get_credentials()` for Redis IAM auth: returns the configured IAM username; signs the **cache name**, not the connection endpoint (ElastiCache's IAM auth signs the cache name — signing the DNS hostname instead produces a signature the server can't verify, which surfaces as an indistinguishable-from-wrong-password `WRONGPASS`); the signed token carries `Action=connect` and the right `User`; the token is presigned with a 900-second expiry and has its `https://` scheme stripped (so it can be sent as a Redis AUTH password); cache names are lowercased before signing (AWS lowercases them at creation time).
- **`test_iam_postgres_backend.py`** — the custom `DatabaseWrapper.get_connection_params()`: when `AWS_IAM_AUTH_ENABLED=True`, generates an RDS auth token via `boto3.client("rds").generate_db_auth_token(...)`, injects it as the password, and forces `sslmode=require`; when disabled, uses the configured static password unchanged and never touches boto3.
- **`test_seed_demo.py`** (`@pytest.mark.slow`, `@pytest.mark.django_db(transaction=True)`) — integration tests for the `seed_demo` management command used to populate a demo environment: creates the expected four projects with the expected suite/run counts and backdated timestamps; is idempotent (re-running wipes and recreates without changing final counts — this now exercises the real async S3-cleanup signal path via `CELERY_TASK_ALWAYS_EAGER`); and produces the expected mix of real screenshots — a passing test with an attached baseline/thumbnail, a failing test with a non-empty diff image, and an unapproved first-upload test (`new_unbaselined_page`) that has a screenshot but explicitly no baseline screenshot and `passed=False`, pinning the manual-approval design at the seed-data level too.

## What's still worth adding

- End-to-end (Playwright/Cypress) coverage against the built Angular SPA — none exists yet; everything above is backend-only.
- Frontend unit tests live under `frontend/` (Vitest + jsdom) and are out of scope for this document.
- A dedicated moto-based (or MinIO-via-testcontainers) integration pack for the raw S3 client paths that the hermetic `FileSystemStorage` swap currently bypasses in most tests — today only the IAM-auth and presigned-URL tests exercise real signing logic; nothing exercises a real S3-compatible `PUT`/`GET` round trip end-to-end.
