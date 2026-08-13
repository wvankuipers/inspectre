# Image diffing

> **Note:** The "Files involved" and "High-level flow" sections below describe the legacy Rails implementation for historical reference. The current Django implementation lives in `backend/core/services/screenshot_comparison.py`.

Two ImageMagick binaries are involved (`identify`, `convert`, `compare`). In the legacy Rails implementation these were invoked via `Open3` shell-out; the Django rebuild uses `subprocess.run`.

## Files involved

| File                                       | Role                                                              |
| ------------------------------------------ | ----------------------------------------------------------------- |
| `app/models/screenshot_comparison.rb`      | Orchestrator. Called from `TestsController#create`.               |
| `app/models/canvas.rb`                     | Computes the comparison canvas size from two `ImageGeometry`s.    |
| `lib/image_geometry.rb`                    | Wraps `identify -verbose <file>`; parses `Geometry: WxH+X+Y`.     |
| `lib/image_processor.rb`                   | Wraps `convert <src> -crop <area> <dest>` for pre-comparison crop. |
| `app/models/thumbnail.rb`                  | Wraps Dragonfly's `.thumb('300x').encode('jpg', '-quality 90')`.  |

## High-level flow (per test)

1. **Crop** (optional, in `TestsController`).
   ```
   convert <uploaded_file> -crop <crop_area> <uploaded_file>     # in-place
   ```
   `crop_area` is an ImageMagick crop spec: `WxH+X+Y` where `+X+Y` is the top-left corner. Example: `640x480+50+100`. **The original file is overwritten** before `Test.create!` runs.

2. **Persist test record** (`Test.create!(test_params)`), which assigns the (cropped) image to `screenshot` via Dragonfly.

3. **Determine the baseline** (`ScreenshotComparison#determine_baseline_image`):
   - Compute the test's `key`.
   - `Baseline.find_by_key(test.key)` →
     - If a Baseline row exists, set `test.screenshot_baseline = baseline.screenshot`. If Dragonfly raises `Dragonfly::Job::Fetch::NotFound` (orphaned UID), fall back to the new screenshot.
     - If no Baseline row exists, set `test.screenshot_baseline = screenshot` (compare against itself → guaranteed pass → first-ever submission becomes the baseline).
   - `test.save!`.

4. **Pad both images** to a shared canvas (`ScreenshotComparison#compare_images` → `Canvas.new`).
   ```
   width  = max(baseline.width, screenshot.width)
   height = max(baseline.height, screenshot.height)
   ```
   Both images are resized via `convert -extent <W>x<H> -background white` so the smaller image gets white padding on the right and bottom. (No anchor, so ImageMagick aligns top-left.)

5. **Compare** with ImageMagick:
   ```
   compare \
     -alpha Off \
     -dissimilarity-threshold 1 \
     -fuzz <fuzz_level> \
     -metric AE \
     -highlight-color '#<highlight_colour>' \
     <padded_baseline> <padded_test> <diff_output>
   ```
   - `-fuzz <pct>` — colour distance tolerance. A pixel within fuzz% of its baseline counterpart counts as identical.
   - `-metric AE` (Absolute Error) — `compare` prints the **count of differing pixels** to stderr.
   - `-dissimilarity-threshold 1` — accept any level of overall dissimilarity (don't error out on "too different").
   - `-alpha Off` — drop alpha channel before compare.
   - `-highlight-color '#XXXXXX'` — colour for differing pixels in the diff image.
   - `<diff_output>` — written to disk; this is the file the UI shows as "Diff".

   The three commands (resize baseline, resize test, compare) are run in serial as a single `popen3` invocation joined by `&&`. The stderr from the last command (the pixel count) is captured and parsed.

6. **Compute pass/fail**:
   ```
   diff_pixels = compare_result.to_f                # parsed from stderr
   img_size    = ImageSize.path(diff_image).size.inject(:*)   # W*H of the diff image
   diff_pct    = (diff_pixels / img_size) * 100
   test.diff   = diff_pct.round(2)
   test.pass   = diff_pct < 0.1
   ```
   The `0.1%` threshold is **hardcoded** (`# TODO: pull out 0.1 (diff threshold to config variable)`). 0.1% of pixels can differ before a test fails.

7. **Persist screenshots** via Dragonfly (`screenshot`, `screenshot_baseline`, `screenshot_diff` accessors). `test.save` triggers the `after_save :update_baseline` hook, which (if `pass` is true) upserts the Baseline.

8. **Generate thumbnails** (`test.create_thumbnails`) — touches `.url` on each thumbnail wrapper to render and cache the 300px JPG.

9. **Clean up** — the three temp PNGs in `tmp/` are deleted.

## Default values

| Parameter         | Default     | Where set                                |
| ----------------- | ----------- | ---------------------------------------- |
| `fuzz_level`      | `30%`       | `Test#default_values` (`after_initialize`) |
| `highlight_colour`| `ff0000`    | `Test#default_values`                     |
| Pass threshold    | `< 0.1`     | Hardcoded in `ScreenshotComparison#determine_pass` |
| Canvas background | `white`     | Hardcoded in `convert -background white -extent ...` |
| Thumbnail width   | `300px`     | Hardcoded in `Thumbnail#create_thumbnail` |
| Thumbnail format  | `jpg q=90`  | Hardcoded in `Thumbnail#create_thumbnail` |

## Failure modes

### Today (legacy bugs)

- ImageMagick not installed → `convert` / `compare` exits non-zero, but the Ruby code does **not check exit codes**. `popen3` reads stderr and discards it on the resize commands. Failures surface only as bad diff numbers or missing files, then `determine_pass` hits a `rescue` block that swallows the exception (`# should probably raise an error here`).
- Crop spec invalid → `ImageProcessor.crop` returns `false`; the controller doesn't react and the test proceeds with whatever state the file is in.
- Baseline screenshot missing in storage (orphan UID) → caught and falls back to self-baseline.
- Identify-verbose output not parseable → `ImageGeometry` returns an instance with `nil` width/height, propagating to `Canvas` which crashes.
- Concurrent posts for the same test key → two requests can both find "no baseline", both set themselves as baseline, last write wins.
- Shell-injection: `fuzz_level`, `highlight_colour`, `crop_area` are interpolated unvalidated into the shell command.

### Rebuild fix

For each of the failure modes above ([decisions.md](decisions.md), "Bugs / risks fixed by the rebuild"):

- Check `subprocess.run().returncode`; treat `compare`'s exit code 1 (images differ) as success but anything ≥ 2 as a hard failure → log structured stderr and return 500.
- Validate `fuzz_level` against `^\d+(\.\d+)?%$`, `highlight_colour` against `^[0-9a-fA-F]{6}$`, and `crop_area` against `^\d+x\d+\+\d+\+\d+$` at the API boundary; reject with 400 before the value reaches a shell.
- Shell-quote every user-derived path with `shlex.quote`, even after validation.
- Wrap the baseline upsert in `transaction.atomic()` + `select_for_update()` (see [data-model.md](data-model.md)) so concurrent posts serialise.
- Treat orphan-UID fallback as a real warning: log it; don't silently treat it as the happy path.

## "Set as baseline" path

When a human clicks the button on a failing test in the UI:

1. Form posts `PATCH /tests/<id>` with `test[baseline]=true`.
2. `TestsController#update` sets `pass = true` and saves.
3. `Test#after_save :update_baseline` upserts the Baseline row, replacing the previous baseline screenshot for that key.
4. Subsequent runs compare against this new baseline.

There is **no audit log** of who/when accepted a baseline. (Auth doesn't exist either, so it would be unattributed anyway.)

## Cropping

Done **before** the test record is created and before any comparison. The crop is destructive on the upload (in-place overwrite). The `Test.crop_area` field is persisted for reference but is not re-applied later.

A common use case: take a full-page screenshot, then submit it with `crop_area` so Spectre only diffs a specific component (e.g. just the header). All baselines are stored in cropped form — there is no "store full, compare cropped" mode.

## Python rebuild — full implementation

Keep the algorithm identical. The diff pipeline lives in three small modules in `core/services/`:

- `image_geometry.py` — wraps `identify` to read width/height.
- `canvas.py` — computes the shared canvas size for two geometries.
- `screenshot_comparison.py` — orchestrates crop → baseline lookup → pad → compare → persist.

### `core/services/image_geometry.py`

```python
import re
import shlex
import subprocess
from dataclasses import dataclass


_GEOMETRY_RE = re.compile(r'(\d+)x(\d+)')


@dataclass(frozen=True)
class ImageGeometry:
    width: int
    height: int

    @classmethod
    def from_file(cls, path: str) -> "ImageGeometry":
        result = subprocess.run(
            f"identify -format '%wx%h' {shlex.quote(path)}",
            shell=True, capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise ImageDiffError(f"identify failed for {path}: {result.stderr.strip()}")
        match = _GEOMETRY_RE.search(result.stdout)
        if not match:
            raise ImageDiffError(f"could not parse identify output: {result.stdout!r}")
        return cls(width=int(match.group(1)), height=int(match.group(2)))


class ImageDiffError(Exception):
    """Raised when ImageMagick fails or produces unparseable output."""
```

### `core/services/canvas.py`

```python
from dataclasses import dataclass
from .image_geometry import ImageGeometry


@dataclass(frozen=True)
class Canvas:
    width: int
    height: int
    dimensions_differ: bool

    @classmethod
    def from_geometries(cls, baseline: ImageGeometry, screenshot: ImageGeometry) -> "Canvas":
        return cls(
            width=max(baseline.width, screenshot.width),
            height=max(baseline.height, screenshot.height),
            dimensions_differ=(baseline.width != screenshot.width
                               or baseline.height != screenshot.height),
        )
```

### `core/services/validation.py`

```python
import re
from rest_framework.exceptions import ValidationError

# Anchored — and remember to .fullmatch(), not .match() — so a payload like
# "30%; rm -rf /" can't slip past the prefix check.
_FUZZ_RE      = re.compile(r'\d+(\.\d+)?%')
_COLOUR_RE    = re.compile(r'[0-9a-fA-F]{6}')
_CROP_RE      = re.compile(r'\d+x\d+\+\d+\+\d+')


def validate_test_params(data):
    """Sanitize POST /tests params before they reach the shell. Raises 400 on bad input."""
    fuzz   = data.get('fuzz_level')      or '30%'
    colour = data.get('highlight_colour') or 'ff0000'
    crop   = data.get('crop_area')

    if not _FUZZ_RE.fullmatch(fuzz):
        raise ValidationError({'fuzz_level': 'must match /^\\d+(\\.\\d+)?%$/'})
    if not _COLOUR_RE.fullmatch(colour):
        raise ValidationError({'highlight_colour': 'must be a 6-char hex string, no leading #'})
    if crop and not _CROP_RE.fullmatch(crop):
        raise ValidationError({'crop_area': 'must match /^\\d+x\\d+\\+\\d+\\+\\d+$/'})

    return {
        'run_id':           data['run_id'],
        'name':             data['name'],
        'browser':          data['browser'],
        'size':             data['size'],
        'source_url':       data.get('source_url'),
        'fuzz_level':       fuzz,
        'highlight_colour': colour,
        'crop_area':        crop,
    }
```

### `core/services/screenshot_comparison.py`

The orchestrator. Reads from the saved `Test`, downloads the previous baseline (if any) from S3, runs the diff, uploads the three result files plus thumbnails, and upserts the `Baseline` row when a comparison actually passes.

```python
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.files import File

from core.models import Baseline

from .baseline_upsert import upsert_baseline_from_test
from .canvas import Canvas
from .image_geometry import ImageDiffError, ImageGeometry
from .thumbnails import attach_test_thumbnails, render_thumbnail

logger = logging.getLogger(__name__)


class ScreenshotComparison:
    """Run the diff pipeline and persist everything for one Test.

    Returns is_new_baseline=True from run() when there is nothing to compare
    this submission against (no Baseline row for the key, or its file is
    missing from storage). In that case the test is stored with no comparison
    images and is NOT marked passed — a human must explicitly approve it via
    the existing "Set as baseline" action before it counts as passing or
    becomes the Baseline for future submissions.
    """

    def __init__(self, test, uploaded_file):
        self.test = test
        self.uploaded_file = uploaded_file

    def run(self) -> bool:
        with tempfile.TemporaryDirectory(prefix="inspectre-") as temp_dir_path:
            tmp = Path(temp_dir_path)
            screenshot_in = self._stage_upload(tmp)
            if self.test.crop_area:
                self._crop_in_place(screenshot_in)

            baseline_in = self._stage_baseline(tmp)
            if baseline_in is None:
                self._record_first_upload(screenshot_in, tmp)
                return True

            paths = {
                "screenshot": tmp / "screenshot.png",
                "baseline": tmp / "baseline.png",
                "diff": tmp / "diff.png",
            }
            canvas = Canvas.from_geometries(
                ImageGeometry.from_file(baseline_in),
                ImageGeometry.from_file(screenshot_in),
            )
            diff_pixels = self._compare(canvas, screenshot_in, baseline_in, paths)
            self._record_result(canvas, diff_pixels)
            self._persist_files(paths)
            attach_test_thumbnails(
                self.test,
                screenshot_path=paths["screenshot"],
                baseline_path=paths["baseline"],
                diff_path=paths["diff"],
                tmp=tmp,
            )

            if self.test.passed:
                upsert_baseline_from_test(self.test)
            return False

    # ---- pipeline steps ----------------------------------------------------

    def _stage_upload(self, tmp: Path) -> Path:
        """Copy Django's UploadedFile chunks into a real path so ImageMagick can read it."""
        dest = tmp / "upload.png"
        with dest.open("wb") as fh:
            for chunk in self.uploaded_file.chunks():
                fh.write(chunk)
        return dest

    def _crop_in_place(self, src: Path) -> None:
        """Apply ImageMagick `-crop` per Test.crop_area, overwriting `src`.

        crop_area is already validated by validate_test_params() at the API
        boundary; this is shell-safe.
        """
        try:
            result = subprocess.run(
                ["convert", str(src), "-crop", self.test.crop_area, "+repage", str(src)],
                capture_output=True,
                text=True,
                check=False,
                timeout=settings.IMAGEMAGICK_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ImageDiffError("ImageMagick timed out") from exc
        if result.returncode != 0:
            logger.error(
                "crop failed",
                extra={
                    "test_id": self.test.id,
                    "stderr": result.stderr.strip(),
                },
            )
            raise ImageDiffError(f"crop failed: {result.stderr.strip()}")

    def _stage_baseline(self, tmp: Path) -> Path | None:
        """Download the current Baseline for this test's key, if one exists in storage.

        Returns None when there's no Baseline row yet for this key, or its file
        is missing from storage (orphan) — both cases mean this submission has
        nothing to compare against and is treated as a first-time upload.
        """
        baseline = Baseline.objects.filter(key=self.test.key).first()
        if not baseline or not baseline.screenshot:
            return None

        baseline_in = tmp / "baseline-in.png"
        try:
            with baseline.screenshot.open("rb") as src, baseline_in.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            return baseline_in
        except FileNotFoundError:
            logger.warning(
                "baseline file missing in storage; treating as first upload",
                extra={"test_id": self.test.id, "key": self.test.key},
            )
            return None
        except Exception as exc:
            raise ImageDiffError(f"failed to read baseline from storage: {exc}") from exc

    def _record_first_upload(self, screenshot_in: Path, tmp: Path) -> None:
        """No valid comparison target exists for this key — either a true
        first-ever upload, or an orphaned Baseline whose file is missing from
        storage. Stored with no comparison images and NOT marked passed: a
        human must explicitly approve it (via the existing "Set as baseline"
        action) before it counts as passing or becomes the Baseline for this
        key. See docs/superpowers/specs/2026-08-13-manual-baseline-approval-design.md.

        Renders the thumbnail (the only step that can fail) before writing
        anything to storage, so a render failure never leaves an orphaned
        storage object behind.
        """
        thumb_path = tmp / "thumb-screenshot.jpg"
        render_thumbnail(screenshot_in, thumb_path)

        self.test.diff = 0
        self.test.passed = False
        with screenshot_in.open("rb") as fh:
            self.test.screenshot.save("original.png", File(fh), save=False)
        with thumb_path.open("rb") as fh:
            self.test.screenshot_thumb.save("thumb-300.jpg", File(fh), save=False)

        self.test.save()

    def _compare(
        self,
        canvas: Canvas,
        screenshot_in: Path,
        baseline_in: Path,
        paths: dict[str, Path],
    ) -> int:
        """Pad both inputs to canvas size, run ImageMagick `compare`,
        return the differing-pixel count parsed from stderr.
        """
        extent = f"{canvas.width}x{canvas.height}"
        pad_cmds = [
            ["convert", str(baseline_in), "-background", "white", "-extent", extent, str(paths["baseline"])],
            ["convert", str(screenshot_in), "-background", "white", "-extent", extent, str(paths["screenshot"])],
        ]
        compare_cmd = [
            "compare",
            "-alpha",
            "Off",
            "-dissimilarity-threshold",
            "1",
            "-fuzz",
            self.test.fuzz_level,
            "-metric",
            "AE",
            "-highlight-color",
            f"#{self.test.highlight_colour}",
            str(paths["baseline"]),
            str(paths["screenshot"]),
            str(paths["diff"]),
        ]
        try:
            for cmd in pad_cmds:
                r = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=settings.IMAGEMAGICK_TIMEOUT_SECONDS,
                )
                if r.returncode != 0:
                    raise ImageDiffError(f"convert pad failed: {r.stderr.strip()}")
            result = subprocess.run(
                compare_cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=settings.IMAGEMAGICK_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ImageDiffError("ImageMagick timed out") from exc
        # `compare` exits 0 when identical, 1 when images differ — both fine.
        # >= 2 is a real failure (corrupt input, missing tool, etc.).
        if result.returncode not in (0, 1):
            logger.error(
                "ImageMagick compare failed",
                extra={
                    "test_id": self.test.id,
                    "returncode": result.returncode,
                    "stderr": result.stderr.strip(),
                },
            )
            raise ImageDiffError(f"compare failed (rc={result.returncode}): {result.stderr.strip()}")

        try:
            return int(result.stderr.strip().split()[0])
        except (ValueError, IndexError) as exc:
            raise ImageDiffError(f"could not parse compare output: {result.stderr!r}") from exc

    def _record_result(self, canvas: Canvas, diff_pixels: int) -> None:
        total_pixels = canvas.width * canvas.height
        diff_percentage = (diff_pixels / total_pixels) * 100 if total_pixels else 0
        self.test.diff = round(diff_percentage, 2)
        self.test.passed = diff_percentage < settings.IMAGE_DIFF_THRESHOLD

    def _persist_files(self, paths: dict[str, Path]) -> None:
        """Attach the three padded result files to the Test's FileFields and save."""
        with paths["screenshot"].open("rb") as fh:
            self.test.screenshot.save("original.png", File(fh), save=False)
        with paths["baseline"].open("rb") as fh:
            self.test.screenshot_baseline.save("baseline.png", File(fh), save=False)
        with paths["diff"].open("rb") as fh:
            self.test.screenshot_diff.save("diff.png", File(fh), save=False)
        self.test.save()
```

### Wiring it up — the `POST /tests` view

`POST /tests` is asynchronous. The view creates the Test row, stages the upload to S3, enqueues a Celery task, and returns immediately with `status=pending`:

```python
test = Test.objects.create(...)   # row exists so the upload-path callable can use instance.id
staging_key = _stage_upload_to_s3(test.id, request.FILES['screenshot'])
process_test.delay(test.id, staging_key)
body = LegacyTestSerializer(test).data
body['is_new_baseline'] = None   # not known yet; worker sets it when done
return Response(body)
```

The Celery worker calls `ScreenshotComparison(test, uploaded_file).run()` and updates `test.status` to `"done"` (or `"failed"`) when complete. Clients poll `GET /tests/:id/status` until the status resolves.

### Things this implementation deliberately does not do

- **No PIL / Wand dependency.** All image work goes through ImageMagick CLI. Adds one less Python dep, makes the failure surface identical to the legacy app, and means an ImageMagick upgrade affects everything in one place.
- **No retry on `compare` failure.** A non-zero exit from `compare` (≥ 2) is always a hard fail — corrupt input or an environment problem — never a transient one. Surface it loudly via `logger.exception` and return 500.
- **No cleanup branch.** `tempfile.TemporaryDirectory()` cleans up automatically on success and on exception, so there's no `finally` block.

### Test surface

This module is the highest-leverage place to test in the rebuild ([tests-and-fixtures.md](tests-and-fixtures.md)). Minimum coverage:

- Identical inputs against an existing baseline → `passed=True`, `diff=0`, no diff highlights, `is_new_baseline=False`.
- No existing Baseline for the key → `passed=False`, `diff=0`, no comparison images, `is_new_baseline=True` — stays unbaselined until a human approves it via "Set as baseline".
- Same dimensions, different content → `passed=False`, diff image has highlight pixels.
- Different dimensions → padded canvas works, `passed=False`.
- `crop_area` valid → cropped image is what gets compared (assert by re-running `identify` on the staged file).
- Shell-injection probe in `fuzz_level` (e.g. `"30%; touch /tmp/pwn"`) → 400 from the view, file does not exist after the call.
- Orphan baseline UID → logs a warning, treats it as a first upload (no comparison images, not passed), `is_new_baseline=True`.
- Concurrent `run()` calls for the same key with no existing Baseline → both are recorded as unbaselined first uploads (`passed=False`), since neither branch upserts a Baseline; no Baseline row is created until a human approves one of them via "Set as baseline".
