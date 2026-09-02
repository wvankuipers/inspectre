"""Synchronous diff pipeline for one POST /tests submission.

Heart of the rebuild. Mirror of the legacy Rails ScreenshotComparison, with
the legacy bugs fixed: shell-injection guards in validation.py, exit-code
checking on every shell-out, race-safe Baseline upsert via select_for_update.
"""

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
        self.test.original_passed = False
        uploaded_fields = []
        try:
            with screenshot_in.open("rb") as fh:
                self.test.screenshot.save("original.png", File(fh), save=False)
            uploaded_fields.append(self.test.screenshot)
            with thumb_path.open("rb") as fh:
                self.test.screenshot_thumb.save("thumb-300.jpg", File(fh), save=False)
            uploaded_fields.append(self.test.screenshot_thumb)
            self.test.save(update_fields=["diff", "passed", "original_passed", "screenshot", "screenshot_thumb"])
        except Exception:
            for field in uploaded_fields:
                try:
                    field.delete(save=False)
                except Exception:
                    logger.warning("failed to clean up orphaned first-upload file: %s", field.name)
            raise

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
        self.test.original_passed = self.test.passed

    def _persist_files(self, paths: dict[str, Path]) -> None:
        """Attach the three padded result files to the Test's FileFields and save."""
        with paths["screenshot"].open("rb") as fh:
            self.test.screenshot.save("original.png", File(fh), save=False)
        with paths["baseline"].open("rb") as fh:
            self.test.screenshot_baseline.save("baseline.png", File(fh), save=False)
        with paths["diff"].open("rb") as fh:
            self.test.screenshot_diff.save("diff.png", File(fh), save=False)
        self.test.save(
            update_fields=["diff", "passed", "original_passed", "screenshot", "screenshot_baseline", "screenshot_diff"]
        )
