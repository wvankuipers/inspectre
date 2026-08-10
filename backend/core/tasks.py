import logging
import tempfile
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings as django_settings
from django.core.files import File

from core.models import Test
from core.services.s3 import get_s3_client
from core.services.screenshot_comparison import ScreenshotComparison
from inspectre.celery import app

logger = logging.getLogger(__name__)


@app.task(bind=True, max_retries=0)
def process_test(self, test_id: int, staging_key: str) -> None:
    """Download a staged upload from S3, run the diff pipeline, and update test status."""
    test = Test.objects.select_related("run__suite__project").get(pk=test_id)
    test.status = Test.STATUS_PROCESSING
    test.save(update_fields=["status"])

    try:
        with tempfile.TemporaryDirectory(prefix="inspectre-") as temp_dir:
            local_path = Path(temp_dir) / "upload.png"
            _download_staged_file(staging_key, local_path)

            with local_path.open("rb") as fh:
                uploaded_file = File(fh, name="upload.png")
                is_new_baseline = ScreenshotComparison(test, uploaded_file).run()

        test.refresh_from_db()
        test.is_new_baseline = is_new_baseline
        test.status = Test.STATUS_DONE
        test.save(update_fields=["status", "is_new_baseline"])

    except Exception:
        logger.exception("process_test failed", extra={"test_id": test_id})
        test.status = Test.STATUS_FAILED
        test.save(update_fields=["status"])

    finally:
        _delete_staged_file(staging_key)


@app.task(bind=True, max_retries=0)
def delete_test_file_keys(self, keys: list[str]) -> None:
    """Delete a Test's S3 storage keys in one batched call. Fired from the
    Test pre_delete signal so bulk cascade deletes (e.g. deleting a Project
    from admin) never block the request on per-row S3 I/O.
    """
    if not keys:
        return

    try:
        response = get_s3_client().delete_objects(
            Bucket=django_settings.AWS_STORAGE_BUCKET_NAME,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
    except (ClientError, BotoCoreError):
        logger.warning("Failed to delete test files", extra={"keys": keys})
        return

    errors = response.get("Errors")
    if errors:
        logger.warning("Failed to delete some test files", extra={"errors": errors})


def _download_staged_file(staging_key: str, destination: Path) -> None:
    get_s3_client().download_file(django_settings.AWS_STORAGE_BUCKET_NAME, staging_key, str(destination))


def _delete_staged_file(staging_key: str) -> None:
    try:
        get_s3_client().delete_object(Bucket=django_settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key)
    except ClientError:
        logger.warning("Failed to delete staged file", extra={"key": staging_key})
