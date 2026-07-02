"""Shared baseline-upsert seam.

Used by:
- ScreenshotComparison (the diff path) — promote a freshly-staged screenshot.
- views/legacy.py PATCH /tests/<id> — promote a previously-failing test's screenshot.
- views/api.py POST /api/tests/<id>/set-baseline/ — same shape, JSON wire format.

All three paths converge here so the select_for_update + thumbnail render is
defined exactly once.
"""

import logging
import tempfile
from pathlib import Path

from django.core.files import File
from django.db import IntegrityError, transaction

from core.models import Baseline

from .thumbnails import attach_baseline_thumbnail

logger = logging.getLogger(__name__)


def upsert_baseline_from_test(test) -> Baseline:
    """Race-safe upsert. The Test row must already have its screenshot attached.

    Mirrors the legacy Test#after_save :update_baseline path: most recent
    passing screenshot wins, baseline.test_id points at the producing Test,
    and the baseline thumbnail is regenerated.
    """
    with transaction.atomic():
        try:
            baseline, _ = Baseline.objects.select_for_update().get_or_create(
                key=test.key,
                defaults={
                    "name": test.name,
                    "browser": test.browser,
                    "size": test.size,
                    "suite_id": test.run.suite_id,
                    "test_id": test.id,
                },
            )
        except IntegrityError:
            # Two concurrent misses raced to insert; the other transaction won.
            # Re-fetch with a lock so we update the row they created.
            baseline = Baseline.objects.select_for_update().get(key=test.key)
        try:
            with test.screenshot.open("rb") as fh:
                baseline.screenshot.save("screenshot.png", File(fh), save=False)
            baseline.test_id = test.id
            baseline.save()
        except Exception:
            logger.exception(
                "baseline upsert failed — storage write error",
                extra={"test_id": test.id, "key": test.key},
            )
            raise

    # Thumbnail is rendered outside the transaction — it's a side effect of the
    # promotion, not part of the atomic invariant.
    with tempfile.TemporaryDirectory(prefix="inspectre-rebaseline-") as tmp_str:
        tmp = Path(tmp_str)
        local_screenshot_path = tmp / "src.png"
        with test.screenshot.open("rb") as src, local_screenshot_path.open("wb") as dst:
            dst.write(src.read())
        baseline.refresh_from_db()
        attach_baseline_thumbnail(baseline, local_screenshot_path, tmp)

    return baseline
