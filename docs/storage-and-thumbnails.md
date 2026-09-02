# Storage & thumbnails

> **Note:** The "Today: Dragonfly" section below describes the legacy Rails image handling for historical reference. The current Django implementation is described in [image-diffing.md](image-diffing.md).

## Today: Dragonfly

Dragonfly is the Rails image-handling library in use. It abstracts:

- where the image bytes live (the **datastore**)
- how URLs are generated to serve them
- on-the-fly transformations (resize, encode)

Configured in `config/initializers/dragonfly.rb`:

```ruby
Dragonfly.app.configure do
  plugin :imagemagick
  secret "5fc2f8d11fb3d4ad28a4c4e3e353d2ca9e041e14930d48a5c1242613f9cdd2cc"   # hardcoded — see open-questions
  url_format "/media/:job/:name"

  if ENV['SCREENSHOT_DATASTORE'] == 'S3'
    datastore :s3,
      bucket_name: ENV['S3_BUCKET_NAME'],
      region: ENV['S3_REGION'],
      access_key_id: ENV['S3_ACCESS_KEY_ID'],
      secret_access_key: ENV['S3_SECRET_ACCESS_KEY']
  else
    datastore :file,
      root_path: Rails.root.join('public/system/dragonfly', Rails.env),
      server_root: Rails.root.join('public')
  end
end

Rails.application.middleware.use Dragonfly::Middleware
```

### Dragonfly behaviour

- `dragonfly_accessor :screenshot` on a model gives you `model.screenshot = <File>` (assigns), `model.screenshot.url` (returns a public URL), `model.screenshot.path` (downloads to a tmp path so shell tools can read it), `model.screenshot.thumb('300x').encode('jpg', '-quality 90')` (lazy thumbnail job), etc.
- The bytes are stored under the column `<accessor>_uid` (e.g. `screenshot_uid`), which holds the datastore key.
- With `:file` datastore: bytes live at `public/system/dragonfly/<env>/<uid>`. The Dragonfly middleware serves them at `/media/...`.
- With `:s3` datastore: bytes live in S3 under `<bucket>/<uid>`. URLs go directly to S3.

### Thumbnails (today)

`app/models/thumbnail.rb` is a thin wrapper that:

1. Renders a 300px-wide JPG (q=90) **once**, on first access.
2. Stores the rendered file at `public/system/dragonfly/<env>/thumbnails/<sha1_of_key>` on **local disk**, regardless of where the original lives.
3. Serves the thumbnail at `/<system/dragonfly/...>` via the Rails public file middleware.
4. Falls back to `public/image_not_found.jpg` if rendering fails.

This means **thumbnails are local even when originals are in S3**. On Heroku-style ephemeral filesystems, thumbnails are lost on every deploy and must be re-rendered. The cache hit is per-instance.

### Files saved per Test

For one Test:
- `screenshot` — the (post-crop) submitted screenshot, padded to canvas size.
- `screenshot_baseline` — the baseline used for comparison, padded to canvas size.
- `screenshot_diff` — the `compare` output (red highlights).

Plus, on first thumbnail access:
- `<sha1>` JPGs in `public/system/dragonfly/<env>/thumbnails/`.

A Run with 50 tests, each 1 MB → ~150 MB of original PNGs on Spectre per run. With a 5-runs retention, a busy suite can be ~750 MB. (Hence why S3 is provided as an option.)

## Rebuild: S3-compatible only

User decision: drop the local-filesystem datastore. Everything goes to object storage (AWS S3, MinIO, GCS via S3 API, Backblaze B2, etc.).

### Layout

Suggested S3 key structure (don't replicate Dragonfly's flat UID format — it's hostile to debugging):

```text
screenshots/staging/<test_id>/upload.png

screenshots/<test_id>/original.png
screenshots/<test_id>/baseline.png
screenshots/<test_id>/diff.png
screenshots/<test_id>/thumb-300.jpg
screenshots/<test_id>/thumb-300-baseline.jpg
screenshots/<test_id>/thumb-300-diff.jpg

baselines/<key>/screenshot.png
baselines/<key>/thumb-300.jpg
```

`screenshots/staging/<test_id>/upload.png` (`staging_key_for_test` in `core/services/s3.py`) is where `POST /tests` stages the raw upload before the async worker picks it up — see "Async pipeline" below. It's also the key the admin queue-recovery actions re-enqueue from when replaying a stuck test.

This makes admin debugging via the S3 console doable.

### Implementation

Use `django-storages` with the S3 backend. The full storage config lives in [deployment-and-config.md](deployment-and-config.md), `settings.py` skeleton — Django 5.x's `STORAGES` dict pointing at `storages.backends.s3.S3Storage`. Don't reproduce it here; one source of truth.

```python
# models.py — originals only; thumbnail fields are added in the Thumbnails section below.
# Each FileField needs a top-level callable, not a closure — Django serializes
# `upload_to` references into migrations and can't import nested functions.

def test_screenshot_path(instance, _original_name):
    return f"screenshots/{instance.id}/original.png"

def test_baseline_path(instance, _original_name):
    return f"screenshots/{instance.id}/baseline.png"

def test_diff_path(instance, _original_name):
    return f"screenshots/{instance.id}/diff.png"

class Test(models.Model):
    screenshot          = models.FileField(upload_to=test_screenshot_path, null=True, blank=True)
    screenshot_baseline = models.FileField(upload_to=test_baseline_path,   null=True, blank=True)
    screenshot_diff     = models.FileField(upload_to=test_diff_path,       null=True, blank=True)
```

Note: `instance.id` is `None` until the row is saved, so the upload-path callable runs **after** the first `Test.objects.create(...)`. The view should `Test.objects.create(name=…, browser=…, …)` first, then assign `test.screenshot = file; test.save()` so the FileField has an `id` to interpolate.

### URL strategy

S3 bucket is private, and URLs are presigned. Every screenshot/baseline/diff/thumbnail URL returned by the API is produced by `core.services.s3.generate_presigned_url`, which signs a time-limited (24h) `GetObject` URL with SigV4 (`Config(signature_version="s3v4")` — botocore's region-dependent default can otherwise fall back to legacy SigV2, which is rejected by KMS-encrypted buckets and doesn't match this design). Presigning uses a dedicated client (`get_presign_s3_client()`) pointed at a browser-reachable endpoint, distinct from the client used for direct upload/download/delete — see [deployment-and-config.md](deployment-and-config.md) for `S3_PUBLIC_BASE_URL`'s role in this.

`AWS_QUERYSTRING_AUTH` and `AWS_S3_CUSTOM_DOMAIN` have been removed from `settings.py` — they only affected django-storages' own `.url()` method, which presigned URLs bypass entirely, so nothing in the codebase read them anymore.

The bucket must deny anonymous/public `s3:GetObject`; access is only via presigned URLs or the IAM/static credentials configured in `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` (used for `PutObject`/`DeleteObject` and for generating presigned URLs).

**Dev exception:** the MinIO setup in `deploy/docker-compose.yml` runs `mc anonymous set download local/inspectre-screenshots` on the `minio-init` service, which grants public anonymous `GetObject` on the whole bucket in local dev. This is a deliberate simplification for local development (lets you open an S3 URL directly in a browser without presigning) — it does not reflect the intended prod (AWS S3) bucket policy, which should keep denying anonymous access as described above.

### Thumbnails in the rebuild

**Render thumbnails as part of the async Celery diff pipeline and upload them alongside originals.** No on-the-fly resizing, no local cache. The legacy app's per-instance thumbnail cache (`<sha1>` JPGs on local disk) is gone — every thumbnail lives in S3 next to its original.

#### `core/services/thumbnails.py`

```python
import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.files import File

from .image_geometry import ImageDiffError

logger = logging.getLogger(__name__)


def render_thumbnail(src: Path, dest: Path) -> None:
    """Resize `src` to a JPG thumbnail at `dest`. Raises ImageDiffError on failure.

    Width is `THUMBNAIL_WIDTH` (default 300), JPEG quality is `THUMBNAIL_JPEG_QUALITY`
    (default 90). Both are env-overridable (decisions.md, "Configuration knobs").
    Runs under `IMAGEMAGICK_TIMEOUT_SECONDS` (default 60) — a hang raises
    ImageDiffError rather than blocking the worker indefinitely.
    """
    try:
        result = subprocess.run(
            [
                "convert",
                str(src),
                "-resize",
                f"{settings.THUMBNAIL_WIDTH}x",
                "-quality",
                str(settings.THUMBNAIL_JPEG_QUALITY),
                str(dest),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=settings.IMAGEMAGICK_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise ImageDiffError("ImageMagick timed out") from exc
    if result.returncode != 0:
        logger.error("thumbnail render failed", extra={
            'src': str(src), 'dest': str(dest),
            'returncode': result.returncode, 'stderr': result.stderr.strip(),
        })
        raise ImageDiffError(f"convert -resize failed: {result.stderr.strip()}")


def attach_test_thumbnails(test, screenshot_path: Path, baseline_path: Path, diff_path: Path,
                           tmp: Path) -> None:
    """Render and attach the three test-row thumbnails to the Test's FileFields.

    Called by ScreenshotComparison after the diff completes. The Test must already
    have an id (the view creates it before invoking the comparison service).
    """
    pairs = [
        (screenshot_path, tmp / 'thumb-screenshot.jpg', test.screenshot_thumb,          'thumb-300.jpg'),
        (baseline_path,   tmp / 'thumb-baseline.jpg',   test.screenshot_baseline_thumb, 'thumb-300-baseline.jpg'),
        (diff_path,       tmp / 'thumb-diff.jpg',       test.screenshot_diff_thumb,     'thumb-300-diff.jpg'),
    ]
    for src, local_dest, field, s3_name in pairs:
        render_thumbnail(src, local_dest)
        with local_dest.open('rb') as fh:
            field.save(s3_name, File(fh), save=False)
    test.save()


def attach_baseline_thumbnail(baseline, screenshot_path: Path, tmp: Path) -> None:
    """Render the baseline's own thumbnail and attach it. Called from the upsert path."""
    local_dest = tmp / 'thumb-baseline-row.jpg'
    render_thumbnail(screenshot_path, local_dest)
    with local_dest.open('rb') as fh:
        baseline.thumbnail.save('thumb-300.jpg', File(fh), save=False)
    baseline.save()
```

The two attach helpers are deliberately separate. `attach_test_thumbnails` lays down the three test-row thumbnails (one per cell in the run page table); `attach_baseline_thumbnail` renders the single thumbnail attached to a Baseline row. Both are invoked from a single shared baseline-upsert wrapper, `upsert_baseline_from_test` (`core/services/baseline_upsert.py`) — used both by the automatic diff pipeline (`ScreenshotComparison.run()`, when the submission passes) and by the manual "Set as baseline" action. There is no separate `self._upsert_baseline` method and no second, independent code path for the manual case — see "Wiring into `screenshot_comparison.py`" below.

`attach_test_thumbnails` also has failure-cleanup logic: if rendering or uploading one of the three thumbnails fails partway through, it deletes any thumbnail fields already saved in that call before re-raising, so a Test never ends up with a stale/orphaned thumbnail left over from a partially-failed attach.

#### Model fields the thumbnails attach to

Add three more `FileField`s to `Test` and one to `Baseline`:

```python
# core/models.py — additions
def test_screenshot_thumb_path(instance, _original_name):
    return f"screenshots/{instance.id}/thumb-300.jpg"

def test_baseline_thumb_path(instance, _original_name):
    return f"screenshots/{instance.id}/thumb-300-baseline.jpg"

def test_diff_thumb_path(instance, _original_name):
    return f"screenshots/{instance.id}/thumb-300-diff.jpg"


class Test(models.Model):
    # ... existing FileFields ...
    screenshot_thumb           = models.FileField(upload_to=test_screenshot_thumb_path, null=True, blank=True)
    screenshot_baseline_thumb  = models.FileField(upload_to=test_baseline_thumb_path,   null=True, blank=True)
    screenshot_diff_thumb      = models.FileField(upload_to=test_diff_thumb_path,       null=True, blank=True)


def baseline_screenshot_path(instance, _original_name):
    return f"baselines/{instance.key}/screenshot.png"

def baseline_thumbnail_path(instance, _original_name):
    return f"baselines/{instance.key}/thumb-300.jpg"


class Baseline(models.Model):
    # ... existing fields ...
    screenshot = models.FileField(upload_to=baseline_screenshot_path, null=True, blank=True)
    thumbnail  = models.FileField(upload_to=baseline_thumbnail_path,  null=True, blank=True)
```

The SPA's API responses serialize `field.url` for each thumbnail, so the SPA never resizes images itself.

#### Wiring into `screenshot_comparison.py`

`ScreenshotComparison.run()` (`core/services/screenshot_comparison.py`) calls `attach_test_thumbnails` after persisting the diff result, then calls the shared `upsert_baseline_from_test` wrapper when the submission passes — that wrapper is what internally renders and attaches the baseline thumbnail:

```python
# Inside ScreenshotComparison.run(), after self._persist_files(paths):
from .baseline_upsert import upsert_baseline_from_test
from .thumbnails import attach_test_thumbnails

attach_test_thumbnails(
    self.test,
    screenshot_path=paths['screenshot'],
    baseline_path=paths['baseline'],
    diff_path=paths['diff'],
    tmp=tmp,
)

if self.test.passed:
    upsert_baseline_from_test(self.test)
```

`upsert_baseline_from_test` (`core/services/baseline_upsert.py`) does the row upsert and then calls `attach_baseline_thumbnail` internally. This is the same function the manual "Set as baseline" action calls — there is no separate inline `self._upsert_baseline` method and no second implementation of the baseline-thumbnail logic.

#### Failure mode

If a `convert -resize` shell-out fails after the diff already succeeded, the test row will have screenshots but no thumbnails — the SPA's `<img onerror>` falls back to the legacy `image_not_found.jpg` ([ui.md](ui.md), "Error and loading states"). `attach_test_thumbnails` logs the failure via `logger.error` and rolls back (deletes) any thumbnails it already saved earlier in that same call before re-raising, so the Test record isn't left with a mismatched partial set. We deliberately don't roll back the Test's screenshot/baseline/diff images themselves: the diff result is still useful even if a thumbnail glitched.

### Async pipeline and temp files

`POST /tests` does **not** run the diff pipeline inline. It creates the `Test` row, stages the raw upload to S3 at `screenshots/staging/<test_id>/upload.png` (`_stage_upload_to_s3`, `core/views/legacy.py`), enqueues `process_test.delay(test.id, staging_key, test.processing_claim)`, and returns immediately with `status=pending` (`backend/core/views/legacy.py:47-73`). Clients poll `GET /tests/<id>/status` until it flips to `done` or `failed`.

The Celery worker's `process_test` task (`core/tasks.py`) downloads the staged upload from S3, guards against concurrent/stale redelivery via a Postgres advisory lock plus a `processing_claim` fencing token, and then runs the actual diff pipeline via `ScreenshotComparison(test, uploaded_file).run()`. That `run()` method is where the steps below happen — in the worker process, not the request handler:

1. Stage the downloaded upload to a local temp file, optionally crop in-place.
2. Stage the previous baseline (if any) from S3 to a temp file.
3. Pad both to a shared canvas, run `compare`.
4. Upload the three result files (original, baseline-snapshot, diff) **plus three thumbnails** to S3.
5. Delete temp files.

`ScreenshotComparison.run()` uses `tempfile.TemporaryDirectory()` in a `with` block so cleanup is automatic on errors.

**First-upload branch:** if there is no usable Baseline for the test's key (a true first-ever submission, or an orphaned Baseline whose file is missing from storage), `run()` takes an early branch — `_record_first_upload()` — instead of the steps above. It renders and stores only `screenshot` and its `screenshot_thumb`; no baseline/diff files or their thumbnails are written, and the test is marked `passed=False`. A human must explicitly promote it via "Set as baseline" before it counts as passing or becomes the Baseline for that key.

## Migration of legacy data

**Decided: no migration** ([decisions.md](decisions.md) #8). The legacy Rails app is being decommissioned; the rebuild starts with empty buckets and a fresh database. The first ingest from each project will self-baseline, and the SPA's "new baseline" badge ([decisions.md](decisions.md) #3) makes that visible.
