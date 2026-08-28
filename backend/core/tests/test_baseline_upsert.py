"""Tests for baseline_upsert error handling."""

import logging
from unittest.mock import patch

import pytest

from core.services.baseline_upsert import upsert_baseline_from_test
from core.services.screenshot_comparison import ScreenshotComparison

pytestmark = [pytest.mark.django_db, pytest.mark.slow]


def test_long_test_key_does_not_truncate_baseline_file_paths(
    project_factory,
    suite_factory,
    run_factory,
    test_factory,
    upload,
    testcard,
):
    """A Test with a long enough name/project/suite combination produces a
    long Test.key / Baseline.key (Test.key can be up to 512 chars). The
    Baseline screenshot and thumbnail paths are
    "baselines/<key>/screenshot.png" and "baselines/<key>/thumb-300.jpg" —
    with a long enough key those paths exceed FileField's default
    max_length of 100, which used to raise SuspiciousFileOperation when the
    storage backend tried to generate/truncate a unique filename.
    Regression test for that bug.

    The key here is deliberately kept well under the 512-char cap that
    Test.key allows: real filesystem storage backends (used here for
    hermetic tests, see the `_filesystem_storage` autouse fixture) enforce
    an OS-level ~255-char limit per path component, which a 512-char key
    alone would blow past for reasons unrelated to the bug being tested
    (that limit doesn't apply to S3, which is what this app uses in
    dev/prod). A key a bit over 100 chars is enough to prove the old
    max_length=100 FileField was insufficient, without hitting that
    unrelated OS ceiling.
    """
    project = project_factory(name="p" * 60)
    suite = suite_factory(project=project, name="s" * 60)
    run = run_factory(suite=suite)
    test = test_factory(run=run, name="t" * 80)

    # Sanity check: this test only proves anything if the key is long enough
    # to overflow the old max_length=100 fields once "baselines/" and
    # "/screenshot.png" are added, but short enough to stay under the
    # filesystem's own per-component name limit.
    assert 100 < len(test.key) < 255

    ScreenshotComparison(test, upload(testcard)).run()
    test.refresh_from_db()
    test.passed = True
    test.save(update_fields=["passed"])

    baseline = upsert_baseline_from_test(test)

    assert baseline.screenshot.name == f"baselines/{test.key}/screenshot.png"
    assert baseline.thumbnail.name == f"baselines/{test.key}/thumb-300.jpg"


def test_storage_write_error_propagates_and_logs(
    test_factory,
    upload,
    testcard,
    caplog,
):
    """If the S3 write inside upsert_baseline_from_test raises, the exception
    propagates to the caller and logger.exception is called with the right
    message — giving operators visibility without swallowing the error.
    """
    # Establish a test with a screenshot attached and passed=True so the
    # upsert path is reached. A first upload no longer auto-passes (manual
    # approval is required), so drive it through .run() for the screenshot,
    # then simulate the human approval step directly.
    test = test_factory()
    ScreenshotComparison(test, upload(testcard)).run()
    test.refresh_from_db()
    test.passed = True
    test.save(update_fields=["passed"])

    storage_error = OSError("S3 write failure")

    caplog.set_level(logging.ERROR, logger="core.services.baseline_upsert")

    with patch(
        "django.db.models.fields.files.FieldFile.save",
        side_effect=storage_error,
    ):
        with pytest.raises(OSError, match="S3 write failure"):
            upsert_baseline_from_test(test)

    assert any("baseline upsert failed" in r.message for r in caplog.records), (
        f"Expected log message not found; got: {[r.message for r in caplog.records]}"
    )
