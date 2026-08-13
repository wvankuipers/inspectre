# Overview

## What Inspectre is

Inspectre is a **visual regression testing service**. CI pipelines (or local scripts) take screenshots during their tests and POST them to Inspectre. Inspectre compares each new screenshot against a stored baseline and reports a pass/fail with a visual diff image.

## Who uses it

Two kinds of clients:

1. **Test runners** (Selenium, Cucumber, or any HTTP client) — they POST screenshots over HTTP.
2. **Humans** browsing the web UI — they look at runs, see which tests failed, eyeball the diff image, and (optionally) click "Set as baseline" to accept a new baseline.

There is no authentication. Anyone with the URL can submit, view, and promote baselines. Django Admin (`/admin/`) uses a single shared staff login for administrative CRUD.

## Core domain concepts

Hierarchy from broadest to narrowest:

```text
Project ──▶ Suite ──▶ Run ──▶ Test
                  └─▶ Baseline   (one per test "key", lives on the Suite)
```

- **Project** — top-level grouping (e.g. "Acme Marketing Site"). Identified by a slug derived from its name.
- **Suite** — a category of tests inside a project (e.g. "Desktop", "Mobile"). Identified by a slug, scoped to its project.
- **Run** — one execution of a suite. Identified by a per-suite **sequential id** (1, 2, 3…). A suite keeps **only the 5 most recent runs**; older runs and their tests are auto-deleted by a post-save signal.
- **Test** — a single screenshot submission within a run. Has a name, browser, size, optional source URL, fuzz level, highlight colour, and optional crop area.
- **Baseline** — the "accepted good" screenshot for a given (project, suite, name, browser, size) tuple. Lives on the Suite. Updated automatically when a test passes against an existing baseline, or when a human clicks "Set as baseline" (which is required for the very first submission of a key, since there's nothing to compare it against and it does not pass automatically).

The (project, suite, name, browser, size) tuple is parameterized into a **key** that ties Tests and Baselines together. See [data-model.md](data-model.md) for the exact key formula.

## End-to-end flow

```text
1. Client creates a run:
     POST /runs { project, suite }            → returns { run_id, ... }

2. Client posts one or more tests on that run:
     POST /tests
       test[run_id]=…
       test[name]=…  test[browser]=…  test[size]=…
       test[screenshot]=<file>
       test[crop_area]=WxH+X+Y          (optional)
       test[fuzz_level]=30%             (optional, default 30%)
       test[highlight_colour]=ff0000    (optional, default ff0000)
       test[source_url]=…               (optional)

3. Inspectre handles each test asynchronously:
   a. Validates params; creates Test(status="pending").
   b. Stages the uploaded file to S3 (`screenshots/staging/<id>/upload.png`).
   c. Enqueues a `process_test` Celery task and returns immediately (~50 ms).
   d. The Celery worker picks up the task and runs the full pipeline:
        i.  If crop_area given → crop the uploaded screenshot first.
        ii. Compute the test "key" from project+suite+name+browser+size.
        iii.Look up the existing baseline for that key.
              - If one exists (and its file is still present in storage), use it as the comparison baseline.
              - If none (or its file is missing), there's nothing to compare against: store the test with no comparison images, mark it `is_new_baseline = true`, and mark it **not passed** — a human must approve it via "Set as baseline" before it counts as passing.
        iv. Pad both images to the same canvas (max width × max height, white background).
        v.  Run ImageMagick compare with -fuzz <fuzz_level> -metric AE
            -highlight-color #<highlight_colour> → diff image + count of differing pixels.
        vi. diff_percentage = (differing_pixels / canvas_area) * 100.
        vii.pass = diff_percentage < 0.1.
        viii.Upload screenshot, baseline-snapshot, and diff image to S3.
            Also generate 300px-wide JPEG thumbnails and upload them.
        ix. If passing (i.e. an existing baseline was compared against and the diff
            was below threshold), upsert a Baseline row for this key. A first
            submission with nothing to compare against does NOT upsert a Baseline
            here — it stays unbaselined until a human approves it.
        x.  Mark is_new_baseline = true if this was a first submission for this key
            (no comparison images, not passed).
        xi. Set status="done" (or "failed" if the pipeline raised).

4. The CI client polls `GET /tests/:id/status` every second until
   `status == "done"` (or "failed"), then returns the completed result to the caller.
   From the caller's perspective the method is still synchronous.

5. Human visits the UI:
     /projects                  → table of all projects + suites with latest run status
     /projects/:p/suites/:s     → suite: latest 5 runs + current baselines (with tabs)
     /projects/:p/suites/:s/runs/:seq
                                → run: every test with baseline | comparison | diff thumbnails
     Click any thumbnail        → image viewer modal: slot navigation + compare slider
     "Set as baseline" button   → POST /api/tests/:id/set-baseline/
```

## Key behaviours

- **Auto-purge of old runs**: a `purge_old_runs` signal fires `post_save` on every Run and deletes everything past the most recent `RUN_RETENTION_PER_SUITE` (default: 5) for that suite.
- **Sequential ids per suite**: Runs get a per-suite sequential id assigned atomically via `select_for_update()` on the Suite row during `Run.save()`.
- **Slug routing**: Projects and Suites use slugs for URLs, auto-updated when the name changes. Renaming breaks existing deep-links and severs all baselines for that project/suite (see [decisions.md](decisions.md) #4).
- **Find-or-create on ingest**: `POST /runs` does `Project.objects.get_or_create(name=…)` then `Suite.objects.get_or_create(project=project, name=…)`. Submitting a screenshot with a new project/suite name silently creates those records.
- **Unbaselined tests require approval**: The first submission for a (project, suite, name, browser, size) has no baseline (or its baseline's file is missing from storage); there's nothing to compare it against, so it's stored with no comparison images, marked **not passed**, and marked `is_new_baseline = true`. The SPA shows a "New baseline" chip so humans can spot these — a human must click "Set as baseline" before the test counts as passing or the screenshot becomes the Baseline for that key.
- **Async image processing**: `POST /tests` returns in ~50 ms. The ImageMagick pipeline runs in a Celery worker backed by Valkey. CI clients poll `GET /tests/:id/status` until `status == "done"`. The SPA shows a "Processing…" chip for any test that has not yet completed and auto-refreshes the run page every 3 s until all tests are terminal.
