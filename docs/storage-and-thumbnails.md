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
screenshots/<test_id>/original.png
screenshots/<test_id>/baseline.png
screenshots/<test_id>/diff.png
screenshots/<test_id>/thumb-300.jpg
screenshots/<test_id>/thumb-300-baseline.jpg
screenshots/<test_id>/thumb-300-diff.jpg

baselines/<key>/screenshot.png
baselines/<key>/thumb-300.jpg
```

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

### Thumbnails in the rebuild

**Render thumbnails synchronously after diff and upload them alongside originals.** No on-the-fly resizing, no local cache. The legacy app's per-instance thumbnail cache (`<sha1>` JPGs on local disk) is gone — every thumbnail lives in S3 next to its original.

#### `core/services/thumbnails.py`

```python
import logging
import shlex
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
    """
    cmd = (
        f"convert {shlex.quote(str(src))} "
        f"-resize {settings.THUMBNAIL_WIDTH}x "
        f"-quality {settings.THUMBNAIL_JPEG_QUALITY} "
        f"{shlex.quote(str(dest))}"
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        logger.exception("thumbnail render failed", extra={
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

The two attach helpers are deliberately separate. `attach_test_thumbnails` lays down the three test-row thumbnails (one per cell in the run page table). `attach_baseline_thumbnail` is the smaller path used when a Baseline is upserted on the suite page.

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

The `ScreenshotComparison.run()` method in [image-diffing.md](image-diffing.md) calls these helpers before `_upsert_baseline`:

```python
# Inside ScreenshotComparison.run(), after _persist_files(paths):
from .thumbnails import attach_test_thumbnails, attach_baseline_thumbnail

attach_test_thumbnails(
    self.test,
    screenshot_path=paths['screenshot'],
    baseline_path=paths['baseline'],
    diff_path=paths['diff'],
    tmp=tmp,
)

if self.test.passed:
    self._upsert_baseline(paths['screenshot'])
    attach_baseline_thumbnail(self.test.baseline, paths['screenshot'], tmp)
```

This adds ~50ms per test to the synchronous `POST /tests` request — acceptable for v1. If `convert -resize` ever becomes the slowest step, batch the three test thumbnails into a single `convert ( a b c ) -resize 300x ... -write a.jpg -write b.jpg -write c.jpg` invocation, but profile first.

#### Failure mode

If a `convert -resize` shell-out fails after the diff already succeeded, the test row will have screenshots but no thumbnails — the SPA's `<img onerror>` falls back to the legacy `image_not_found.jpg` ([ui.md](ui.md), "Error and loading states"). The `logger.exception` call surfaces the failure to the operator without breaking the request. We deliberately don't roll back the Test record: the diff result is still useful even if a thumbnail glitched.

### Image processing temp files

Each `POST /tests` needs to:
1. Receive the upload (in `request.FILES['test[screenshot]']`).
2. Optionally crop in-place (overwrite the temp).
3. Download the previous baseline from S3 to a temp file.
4. Pad both, run `compare`.
5. Upload the three result files (original, baseline-snapshot, diff) **plus three thumbnails** to S3.
6. Delete temp files.

Use `tempfile.TemporaryDirectory()` in a `with` block so cleanup is automatic on errors. Don't use the request handler's tempfile path directly; copy first.

## Migration of legacy data

**Decided: no migration** ([decisions.md](decisions.md) #8). The legacy Rails app is being decommissioned; the rebuild starts with empty buckets and a fresh database. The first ingest from each project will self-baseline, and the SPA's "new baseline" badge ([decisions.md](decisions.md) #3) makes that visible.
