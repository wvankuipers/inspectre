"""Thumbnail rendering. ImageMagick `convert -resize`, results uploaded to S3
alongside their originals. No on-the-fly resizing, no local cache layer.
"""

import logging
import subprocess
from pathlib import Path

from django.conf import settings
from django.core.files import File

from .image_geometry import ImageDiffError

logger = logging.getLogger(__name__)


def render_thumbnail(src: Path, dest: Path) -> None:
    """Resize `src` to a JPG thumbnail at `dest`. Raises ImageDiffError on failure.

    Width is THUMBNAIL_WIDTH (default 300), JPEG quality is THUMBNAIL_JPEG_QUALITY
    (default 90). Both are env-overridable.
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
        logger.error(
            "thumbnail render failed",
            extra={
                "src": str(src),
                "dest": str(dest),
                "returncode": result.returncode,
                "stderr": result.stderr.strip(),
            },
        )
        raise ImageDiffError(f"convert -resize failed: {result.stderr.strip()}")


def attach_test_thumbnails(
    test,
    screenshot_path: Path,
    baseline_path: Path,
    diff_path: Path,
    tmp: Path,
) -> None:
    """Render and attach the three test-row thumbnails (one per cell in the run table).

    Called by ScreenshotComparison after the diff result is persisted.
    """
    pairs = [
        (screenshot_path, tmp / "thumb-screenshot.jpg", "screenshot_thumb", "thumb-300.jpg"),
        (baseline_path, tmp / "thumb-baseline.jpg", "screenshot_baseline_thumb", "thumb-300-baseline.jpg"),
        (diff_path, tmp / "thumb-diff.jpg", "screenshot_diff_thumb", "thumb-300-diff.jpg"),
    ]
    uploaded_fields = []
    try:
        for src, local_dest, field_name, s3_name in pairs:
            render_thumbnail(src, local_dest)
            field = getattr(test, field_name)
            with local_dest.open("rb") as fh:
                field.save(s3_name, File(fh), save=False)
            uploaded_fields.append(field)
        test.save()
    except Exception:
        for field in uploaded_fields:
            try:
                field.delete(save=False)
            except Exception:
                logger.warning("failed to clean up orphaned thumbnail: %s", field.name)
        raise


def attach_baseline_thumbnail(baseline, screenshot_path: Path, tmp: Path) -> None:
    """Render the baseline's own thumbnail (used on the suite page) and attach it."""
    local_dest = tmp / "thumb-baseline-row.jpg"
    render_thumbnail(screenshot_path, local_dest)
    with local_dest.open("rb") as fh:
        baseline.thumbnail.save("thumb-300.jpg", File(fh), save=False)
    baseline.save()
