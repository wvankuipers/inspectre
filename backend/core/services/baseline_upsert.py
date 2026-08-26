"""Shared baseline-upsert seam.

Three functions, composed differently by their callers:
- `upsert_baseline_row` + `attach_baseline_thumbnail_for_test` — called
  directly (outside the row-upsert's own transaction) by
  `views/legacy._set_as_baseline`, shared by views/legacy.py PATCH
  /tests/<id> and views/api.py POST /api/tests/<id>/set-baseline/, so the
  test's own `test.save()` can be wrapped in the same atomic block as the
  Baseline row write.
- `upsert_baseline_from_test` — the combined wrapper (row upsert then
  thumbnail, no surrounding transaction needed) used by ScreenshotComparison
  (the diff path) and `seed_demo`.

The DB/storage upsert (`upsert_baseline_row`) and the thumbnail render
(`attach_baseline_thumbnail_for_test`) are each defined exactly once; callers
choose how to sequence them around their own transaction boundaries.
"""

import logging
import tempfile
from pathlib import Path

from django.core.files import File
from django.db import IntegrityError, transaction

from core.models import Baseline

from .thumbnails import attach_baseline_thumbnail

logger = logging.getLogger(__name__)


def upsert_baseline_row(test) -> Baseline:
    """Atomic DB+storage write: get-or-create the Baseline row and attach
    test's screenshot as its image. Callers that need test.save() to roll
    back together with this must call it inside their own transaction.atomic()."""
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
    return baseline


def attach_baseline_thumbnail_for_test(baseline, test) -> None:
    """Render/attach the baseline thumbnail. Side effect only — not part of
    any atomic invariant; failure here does not undo the row upsert above."""
    with tempfile.TemporaryDirectory(prefix="inspectre-rebaseline-") as tmp_str:
        tmp = Path(tmp_str)
        local_screenshot_path = tmp / "src.png"
        with test.screenshot.open("rb") as src, local_screenshot_path.open("wb") as dst:
            dst.write(src.read())
        baseline.refresh_from_db()
        attach_baseline_thumbnail(baseline, local_screenshot_path, tmp)


def upsert_baseline_from_test(test) -> Baseline:
    """Race-safe upsert. The Test row must already have its screenshot attached.

    Mirrors the legacy Test#after_save :update_baseline path: most recent
    passing screenshot wins, baseline.test_id points at the producing Test,
    and the baseline thumbnail is regenerated. Unchanged public entry point —
    existing callers (ScreenshotComparison, the SPA set-baseline endpoint via
    _set_as_baseline) keep this exact behavior.
    """
    baseline = upsert_baseline_row(test)
    attach_baseline_thumbnail_for_test(baseline, test)
    return baseline
