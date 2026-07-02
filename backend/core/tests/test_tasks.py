from unittest.mock import MagicMock, patch

import pytest

from core.models import Test
from core.tasks import process_test

pytestmark = pytest.mark.django_db


class TestProcessTestTask:
    def test_sets_status_to_done_on_success(self, test_factory, settings, tmp_path):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file"),
        ):
            mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
            mock_instance = MagicMock()
            mock_instance.run.return_value = False
            mock_cls.return_value = mock_instance

            process_test.delay(test.id, "screenshots/staging/1/upload.png")

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE

    def test_sets_is_new_baseline_from_comparison_result(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file"),
        ):
            mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
            mock_instance = MagicMock()
            mock_instance.run.return_value = True  # is_new_baseline = True
            mock_cls.return_value = mock_instance

            process_test.delay(test.id, "screenshots/staging/1/upload.png")

        test.refresh_from_db()
        assert test.is_new_baseline is True

    def test_sets_status_to_failed_on_exception(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = False
        test = test_factory()

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file"),
        ):
            mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
            mock_instance = MagicMock()
            mock_instance.run.side_effect = RuntimeError("imagemagick died")
            mock_cls.return_value = mock_instance

            process_test.delay(test.id, "screenshots/staging/1/upload.png")

        test.refresh_from_db()
        assert test.status == Test.STATUS_FAILED

    def test_transitions_through_processing_before_done(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()
        statuses_seen = []

        def fake_run():
            test.refresh_from_db()
            statuses_seen.append(test.status)
            return False

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file"),
        ):
            mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
            mock_instance = MagicMock()
            mock_instance.run.side_effect = fake_run
            mock_cls.return_value = mock_instance

            process_test.delay(test.id, "screenshots/staging/1/upload.png")

        assert Test.STATUS_PROCESSING in statuses_seen
