"""Tests for baseline_upsert error handling."""

import logging
from unittest.mock import patch

import pytest

from core.services.baseline_upsert import upsert_baseline_from_test
from core.services.screenshot_comparison import ScreenshotComparison

pytestmark = [pytest.mark.django_db, pytest.mark.slow]


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
    # Establish a passing test with a screenshot attached so the upsert path
    # is reached (the test must be marked passed with a screenshot already saved).
    test = test_factory()
    ScreenshotComparison(test, upload(testcard)).run()
    # Fetch the test that now has a screenshot attached and passed=True.
    test.refresh_from_db()
    assert test.passed is True

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
