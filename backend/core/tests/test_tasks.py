from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.conf import settings as django_settings

from core.models import Test
from core.tasks import delete_test_file_keys, process_test

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


class TestDeleteTestFileKeysTask:
    def test_noop_for_empty_keys(self, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True

        with patch("core.tasks.get_s3_client") as mock_get_client:
            delete_test_file_keys.delay([])

        mock_get_client.assert_not_called()

    def test_batches_all_keys_into_one_delete_objects_call(self, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        keys = [
            "screenshots/1/original.png",
            "screenshots/1/baseline.png",
            "screenshots/1/diff.png",
        ]

        with patch("core.tasks.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.delete_objects.return_value = {"Deleted": [{"Key": k} for k in keys]}
            mock_get_client.return_value = mock_client

            delete_test_file_keys.delay(keys)

        mock_client.delete_objects.assert_called_once_with(
            Bucket=django_settings.AWS_STORAGE_BUCKET_NAME,
            Delete={"Objects": [{"Key": k} for k in keys], "Quiet": True},
        )

    def test_logs_but_does_not_raise_on_partial_s3_errors(self, settings, caplog):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        keys = ["screenshots/1/original.png", "screenshots/1/baseline.png"]

        with patch("core.tasks.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.delete_objects.return_value = {
                "Errors": [{"Key": "screenshots/1/baseline.png", "Code": "AccessDenied", "Message": "nope"}]
            }
            mock_get_client.return_value = mock_client

            delete_test_file_keys.delay(keys)  # must not raise

        assert "screenshots/1/baseline.png" in caplog.text

    def test_logs_but_does_not_raise_on_client_error(self, settings, caplog):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        keys = ["screenshots/1/original.png"]

        with patch("core.tasks.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.delete_objects.side_effect = ClientError(
                {"Error": {"Code": "500", "Message": "boom"}}, "DeleteObjects"
            )
            mock_get_client.return_value = mock_client

            delete_test_file_keys.delay(keys)  # must not raise
