import logging
import tempfile
from pathlib import Path

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings as django_settings
from django.core.files import File
from django.db import connection

from core.models import Test
from core.services.s3 import get_s3_client
from core.services.screenshot_comparison import ScreenshotComparison
from inspectre.celery import app

logger = logging.getLogger(__name__)

# Arbitrary namespace id reserved for the process_test advisory lock family.
# Passed as the first arg to the two-argument pg_try_advisory_lock/pg_advisory_unlock
# forms so this lock's keyspace (test_id) never collides with an unrelated feature
# that might someday lock on some other model's PK using the same numeric id.
_PROCESS_TEST_LOCK_NAMESPACE = 1


@app.task(bind=True, max_retries=0)
def process_test(self, test_id: int, staging_key: str) -> None:
    """Download a staged upload from S3, run the diff pipeline, and update test status.

    Guarded by a Postgres session advisory lock keyed on `test_id`: if this
    exact test is already being processed by another invocation (e.g. a
    worker-crash redelivery racing a manual admin restart), this invocation
    backs off immediately instead of racing it on the shared staging key and
    Test row fields.

    Assumes a direct Postgres connection per session (no transaction-pooling
    proxy like PgBouncer transaction-mode or RDS Proxy without pinning); this
    project doesn't use one today, but do not introduce one without revisiting
    this.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test_id])
        acquired = cursor.fetchone()[0]

    if not acquired:
        logger.warning(
            "process_test: test %s is already being processed by another invocation, skipping",
            test_id,
            extra={"test_id": test_id},
        )
        return

    try:
        test = Test.objects.select_related("run__suite__project").get(pk=test_id)
        test.process_attempts += 1

        if test.process_attempts > django_settings.PROCESS_TEST_MAX_ATTEMPTS:
            logger.error(
                "process_test: test %s attempt %s exceeded max attempts (%s), marking failed without reprocessing",
                test_id,
                test.process_attempts,
                django_settings.PROCESS_TEST_MAX_ATTEMPTS,
                extra={"test_id": test_id, "process_attempts": test.process_attempts},
            )
            test.status = Test.STATUS_FAILED
            test.save(update_fields=["process_attempts", "status"])
            _delete_staged_file(staging_key)
            return

        # The incremented attempt counter must be persisted BEFORE the risky pipeline
        # work below runs, not after. This is what makes the cap effective across a
        # worker-crash redelivery: if the process dies mid-pipeline, the count is
        # already committed, so the retry sees the incremented value. Moving this
        # save to after the pipeline would silently defeat the whole mechanism.
        test.status = Test.STATUS_PROCESSING
        test.save(update_fields=["process_attempts", "status"])

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

    finally:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test_id])
                released = cursor.fetchone()[0]
            if not released:
                logger.warning(
                    "process_test: pg_advisory_unlock found no lock held for test %s",
                    test_id,
                    extra={"test_id": test_id},
                )
        except Exception:
            logger.warning(
                "process_test: failed to release advisory lock for test %s", test_id, extra={"test_id": test_id}
            )


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
