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
from .thumbnails import attach_test_thumbnails

logger = logging.getLogger(__name__)


class ScreenshotComparison:
    """Run the diff pipeline and persist everything for one Test.

    Returns is_new_baseline=True from run() when this submission established the
    first Baseline for the Test's key (decisions.md #3).
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

            baseline_in, is_new_baseline = self._stage_baseline(tmp, screenshot_in)

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
                # is_new_baseline only meaningful when this submission passed.
                return is_new_baseline
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

    def _stage_baseline(
        self,
        tmp: Path,
        screenshot_in: Path,
    ) -> tuple[Path, bool]:
        """Download the previous baseline if one exists; otherwise self-baseline.

        Returns (path-to-baseline-on-disk, is_new_baseline).
        """
        baseline = Baseline.objects.filter(key=self.test.key).first()
        baseline_in = tmp / "baseline-in.png"

        if baseline and baseline.screenshot:
            try:
                with baseline.screenshot.open("rb") as src, baseline_in.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                return baseline_in, False
            except FileNotFoundError:
                logger.warning(
                    "baseline file missing in storage; self-baselining",
                    extra={"test_id": self.test.id, "key": self.test.key},
                )
            except Exception as exc:
                raise ImageDiffError(f"failed to read baseline from storage: {exc}") from exc

        # No baseline (or orphan UID) → compare the new screenshot against itself.
        # The diff is guaranteed zero, the test passes, and this submission
        # becomes the new baseline.
        shutil.copy(screenshot_in, baseline_in)
        return baseline_in, True

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
