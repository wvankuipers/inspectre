import subprocess
from unittest.mock import patch

import pytest

from core.models import Baseline
from core.services.baseline_upsert import upsert_baseline_from_test
from core.services.image_geometry import ImageDiffError, ImageGeometry
from core.services.screenshot_comparison import ScreenshotComparison
from core.views.legacy import _set_as_baseline

pytestmark = [pytest.mark.django_db, pytest.mark.slow]


def _approve(test) -> None:
    """Simulate a human clicking "Set as baseline" on a test that just went
    through the no-comparison path, so a subsequent submission for the same
    key has something real to compare against.
    """
    test.refresh_from_db()
    test.passed = True
    test.save(update_fields=["passed"])
    upsert_baseline_from_test(test)


# ---- Happy paths -----------------------------------------------------------


def test_first_upload_requires_manual_approval(test_factory, upload, testcard):
    """First-ever submission for a key has nothing to compare against → stored
    with no comparison images, marked NOT passed, and no Baseline is created.
    A human must explicitly approve it before it counts as passing.

    decisions.md #3 (superseded): auto-self-baseline is replaced by manual
    approval — nothing passes without a human having looked at it.
    """
    test = test_factory()
    is_new = ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    assert test.passed is False
    assert test.diff == 0
    assert is_new is True
    assert not test.screenshot_baseline
    assert not test.screenshot_diff
    assert test.screenshot
    assert test.screenshot_thumb
    assert not Baseline.objects.filter(key=test.key).exists()


def test_approving_a_first_upload_establishes_the_baseline(test_factory, upload, testcard):
    """The existing 'Set as baseline' mechanism promotes an unapproved first
    upload exactly like any other test: flips passed=True and creates the
    Baseline row. No special-casing needed for tests that came from the
    no-comparison path.
    """
    test = test_factory()
    ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    assert test.passed is False
    assert not Baseline.objects.filter(key=test.key).exists()

    _set_as_baseline(test)

    test.refresh_from_db()
    assert test.passed is True
    baseline = Baseline.objects.get(key=test.key)
    assert baseline.screenshot
    assert baseline.test_id == test.id


def test_identical_to_baseline_passes(test_factory, upload, testcard):
    """Re-submitting the same image after a baseline exists → pass, is_new_baseline=False."""
    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()
    _approve(first)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    is_new = ScreenshotComparison(second, upload(testcard)).run()

    second.refresh_from_db()
    assert second.passed is True
    assert is_new is False


def test_different_image_fails(test_factory, upload, run1, run2):
    """Pair with intentional differences → diff% > threshold → fail."""
    first = test_factory()
    ScreenshotComparison(first, upload(run1)).run()
    _approve(first)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    ScreenshotComparison(second, upload(run2)).run()

    second.refresh_from_db()
    assert second.passed is False
    assert second.diff > 0.1
    assert second.screenshot_diff  # diff image attached


# ---- Canvas padding --------------------------------------------------------


def test_different_dimensions_pads_to_larger_canvas(
    test_factory,
    upload,
    testcard,
    testcard_large,
):
    """400x300 vs 500x375 → canvas is 500x375; the diff fills the padded region."""
    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()
    _approve(first)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    ScreenshotComparison(second, upload(testcard_large)).run()

    second.refresh_from_db()
    geometry = ImageGeometry.from_file(second.screenshot_diff.path)
    assert geometry.width == 500
    assert geometry.height == 375


# ---- Crop ------------------------------------------------------------------


def test_crop_area_uses_cropped_region(test_factory, upload, testcard):
    """crop_area=200x150+0+0 → only the top-left 200x150 of testcard is compared."""
    test = test_factory(crop_area="200x150+0+0")
    ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    geometry = ImageGeometry.from_file(test.screenshot.path)
    assert geometry.width == 200
    assert geometry.height == 150


# ---- Failure modes (ImageMagick) ------------------------------------------


def test_corrupt_input_raises_imagediff_error(test_factory, upload, tmp_path):
    """ImageMagick failures don't silently succeed — the legacy bare-rescue is gone.

    decisions.md, "Bugs / risks fixed by the rebuild": exit codes >= 2 raise.
    """
    not_an_image = tmp_path / "not_an_image.png"
    not_an_image.write_bytes(b"this is not a PNG")

    test = test_factory()
    with pytest.raises(ImageDiffError):
        ScreenshotComparison(test, upload(not_an_image)).run()


def test_first_upload_thumbnail_failure_leaves_no_orphaned_screenshot(
    test_factory,
    upload,
    testcard,
):
    """On a first upload, render_thumbnail runs before any storage write. If it
    raises, nothing has been saved to storage or the DB yet — no orphaned file.

    Regression test for the ordering fix in _record_first_upload: previously
    the screenshot was saved to storage before the thumbnail was rendered, so
    a thumbnail failure left an unreachable file in storage (never saved to
    the DB row, so nothing would ever clean it up).
    """
    test = test_factory()

    with patch("core.services.screenshot_comparison.render_thumbnail", side_effect=ImageDiffError("boom")):
        with pytest.raises(ImageDiffError, match="boom"):
            ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    assert not test.screenshot
    assert not test.screenshot_thumb
    assert not Baseline.objects.filter(key=test.key).exists()


def test_imagemagick_timeout_raises_imagediff_error(test_factory, upload, testcard):
    """If ImageMagick hangs past the timeout, ImageDiffError is raised immediately.

    We test via _crop_in_place, which is the first subprocess.run call owned by
    ScreenshotComparison (before the image_geometry identify calls). crop_area is
    set so the crop path is exercised, and we patch subprocess.run to raise
    TimeoutExpired on the first call it receives.
    """
    test = test_factory(crop_area="200x150+0+0")

    real_run = subprocess.run
    call_count = {"n": 0}

    def timeout_on_first(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise subprocess.TimeoutExpired(cmd=args[0] if args else "convert", timeout=60)
        return real_run(*args, **kwargs)

    with patch("subprocess.run", side_effect=timeout_on_first):
        with pytest.raises(ImageDiffError, match="timed out"):
            ScreenshotComparison(test, upload(testcard)).run()


def test_orphan_baseline_requires_manual_reapproval(
    test_factory,
    upload,
    testcard,
    caplog,
):
    """Baseline row exists but its screenshot file is gone from storage →
    treated exactly like a first upload: log warning, no comparison, NOT
    passed. The stale Baseline row is left as-is (still orphaned) — approving
    the new test is what fixes it via upsert_baseline_from_test.
    """
    import logging

    caplog.set_level(logging.WARNING, logger="core.services.screenshot_comparison")

    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()

    # Since Task 1's change, `first` never created a Baseline row in the
    # first place (it required approval too) — so establish one directly to
    # exercise the orphan path in isolation from the approval flow.
    _approve(first)

    baseline = Baseline.objects.get(key=first.key)
    baseline.screenshot.storage.delete(baseline.screenshot.name)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    is_new = ScreenshotComparison(second, upload(testcard)).run()

    second.refresh_from_db()
    assert is_new is True
    assert second.passed is False
    assert any("baseline file missing" in r.message for r in caplog.records)


# ---- Thumbnails (slice 4c) -------------------------------------------------


def test_passing_run_populates_all_test_thumbnails(test_factory, upload, testcard):
    """Three test-row thumbnails (screenshot, baseline, diff) attach when a real
    comparison happens and passes — i.e. a baseline already existed."""
    first = test_factory()
    ScreenshotComparison(first, upload(testcard)).run()
    _approve(first)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    ScreenshotComparison(second, upload(testcard)).run()

    second.refresh_from_db()
    assert second.screenshot_thumb
    assert second.screenshot_baseline_thumb
    assert second.screenshot_diff_thumb


def test_first_upload_only_populates_screenshot_thumbnail(test_factory, upload, testcard):
    """First-ever submission has nothing to compare against: only the received
    screenshot gets a thumbnail. There's no baseline/diff thumbnail yet."""
    test = test_factory()
    ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    assert test.screenshot_thumb
    assert not test.screenshot_baseline_thumb
    assert not test.screenshot_diff_thumb


def test_failing_run_still_populates_test_thumbnails(
    test_factory,
    upload,
    run1,
    run2,
):
    """Diff thumbnails are useful for debugging the fail; render even on failure."""
    first = test_factory()
    ScreenshotComparison(first, upload(run1)).run()
    _approve(first)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    ScreenshotComparison(second, upload(run2)).run()

    second.refresh_from_db()
    assert second.passed is False
    assert second.screenshot_thumb
    assert second.screenshot_baseline_thumb
    assert second.screenshot_diff_thumb


def test_baseline_thumbnail_attached_on_pass(test_factory, upload, testcard):
    """The Baseline row gets its own thumbnail (used on the suite page)."""
    test = test_factory()
    ScreenshotComparison(test, upload(testcard)).run()
    _approve(test)

    baseline = Baseline.objects.get(key=test.key)
    assert baseline.thumbnail


def test_thumbnail_width_matches_setting(
    settings,
    test_factory,
    upload,
    testcard,
):
    """THUMBNAIL_WIDTH controls the rendered width."""
    settings.THUMBNAIL_WIDTH = 150

    test = test_factory()
    ScreenshotComparison(test, upload(testcard)).run()

    test.refresh_from_db()
    geometry = ImageGeometry.from_file(test.screenshot_thumb.path)
    assert geometry.width == 150


# ---- Configurable threshold (decisions.md #2) -----------------------------


def test_pass_threshold_is_configurable(
    settings,
    test_factory,
    upload,
    run1,
    run2,
):
    """IMAGE_DIFF_THRESHOLD env var changes pass/fail without code changes."""
    settings.IMAGE_DIFF_THRESHOLD = 100.0  # accept any diff

    first = test_factory()
    ScreenshotComparison(first, upload(run1)).run()
    _approve(first)

    second = test_factory(
        run=first.run,
        name=first.name,
        browser=first.browser,
        size=first.size,
    )
    ScreenshotComparison(second, upload(run2)).run()

    second.refresh_from_db()
    assert second.passed is True  # would have been False with the default 0.1
