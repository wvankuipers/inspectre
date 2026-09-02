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

# Bounds on the requeue-on-lock-contention behavior below: how many times we'll
# re-enqueue ourselves while another invocation holds the lock, and how long to
# wait between attempts.
_MAX_LOCK_WAIT_REQUEUES = 20
_LOCK_WAIT_COUNTDOWN_SECONDS = 15


@app.task(bind=True, max_retries=0)
def process_test(self, test_id: int, staging_key: str, claimed_processing: int, lock_wait_attempts: int = 0) -> None:
    """Download a staged upload from S3, run the diff pipeline, and update test status.

    Guarded by a Postgres session advisory lock keyed on `test_id`: if this
    exact test is already being processed by another invocation (e.g. a
    worker-crash redelivery racing a manual admin restart), this invocation
    requeues itself instead of racing it on the shared staging key and Test
    row fields (see the requeue paragraph below for the retry/give-up
    mechanics).

    That advisory lock only prevents CONCURRENT invocations from racing each
    other — it does nothing to stop a stale invocation from running to
    completion SEQUENTIALLY after a newer attempt has already superseded it
    (e.g. a double-clicked admin restart, or a worker-crash redelivery of an
    old attempt arriving after a newer manual restart already completed).
    `claimed_processing` guards against that: it's the `processing_claim`
    fencing token that was current on the Test row at the moment this
    invocation was enqueued. Immediately after acquiring the lock and
    fetching the row, we compare it against the row's CURRENT
    `processing_claim`; if they don't match, a newer claim has since
    superseded this delivery and we exit without touching `status`,
    `process_attempts`, or the staged file.

    Neither of the above catches a THIRD case: the SAME message (identical
    `test_id`/`staging_key`/`claimed_processing`) redelivered by the broker
    after the original delivery has already run to full completion. This can
    happen with `CELERY_TASK_ACKS_LATE=True` on a Redis broker independent of
    any crash (Redis's visibility-timeout mechanism can re-queue a message
    that's taking "too long" even though the original consumer is still
    running or has just finished) — a known Celery+Redis footgun. Since
    `processing_claim` never changed, the fencing check above would report a
    match and let the duplicate proceed, re-running the pipeline against a
    now-deleted staged file and overwriting a good `STATUS_DONE` result with
    `STATUS_FAILED`. We guard against this by checking whether the row has
    already reached a terminal status (`STATUS_DONE`/`STATUS_FAILED`) for
    this exact claim; if so, this is a duplicate delivery of an
    already-finished attempt and we bail out immediately.

    None of the first three guards catch a FOURTH case either: a currently
    RUNNING invocation gets superseded MID-FLIGHT (e.g. an admin restarts the
    same row while this invocation's pipeline — ImageMagick, S3 I/O — is still
    executing). The claim and terminal-status checks above only run ONCE, at
    the very start, so a stale-but-already-running invocation would otherwise
    sail through to the end using stale data, overwrite the row with the
    wrong terminal result, and delete the staged upload the newer attempt
    still needs. We close this by re-checking `processing_claim` again AFTER
    the pipeline finishes (and after `refresh_from_db()` picks up any
    concurrent change) and gating BOTH the terminal status write and the
    staged-file deletion behind that second check. Relatedly, when the
    advisory lock itself is contended (a newer invocation racing a still-
    running older one), we no longer just drop the message: we requeue it via
    `apply_async` with an incremented `lock_wait_attempts`, up to
    `_MAX_LOCK_WAIT_REQUEUES`, so a losing invocation gets another chance
    instead of vanishing forever the instant Celery acks its message.

    `ScreenshotComparison(test, uploaded_file).run()` writes its own
    `screenshot`/`screenshot_baseline`/`screenshot_diff`/thumbnail FileFields
    to S3 and saves them to the DB from inside its own `run()` call, before
    this function gets a chance to revalidate the claim afterward. Those
    internal saves (in `ScreenshotComparison` and `attach_test_thumbnails`)
    are scoped with an explicit `update_fields` list that never includes
    `processing_claim`, `status`, or `process_attempts` — so they can never
    clobber those columns back to this invocation's own stale in-memory
    values, no matter when a concurrent restart's claim bump lands relative
    to them. That's what makes the mid-flight revalidation above trustworthy
    rather than merely best-effort: nothing between the initial claim check
    and the final one can silently undo it.

    Assumes a direct Postgres connection per session (no transaction-pooling
    proxy like PgBouncer transaction-mode or RDS Proxy without pinning); this
    project doesn't use one today, but do not introduce one without revisiting
    this.
    """
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test_id])
        acquired = cursor.fetchone()[0]

    if not acquired:
        if lock_wait_attempts >= _MAX_LOCK_WAIT_REQUEUES:
            logger.error(
                "process_test: test %s still locked by another invocation after %s requeue attempts, giving up",
                test_id,
                lock_wait_attempts,
                extra={"test_id": test_id, "lock_wait_attempts": lock_wait_attempts},
            )
            return
        logger.warning(
            "process_test: test %s is locked by another invocation, requeuing (attempt %s/%s)",
            test_id,
            lock_wait_attempts + 1,
            _MAX_LOCK_WAIT_REQUEUES,
            extra={"test_id": test_id, "lock_wait_attempts": lock_wait_attempts},
        )
        process_test.apply_async(
            args=[test_id, staging_key, claimed_processing, lock_wait_attempts + 1],
            countdown=_LOCK_WAIT_COUNTDOWN_SECONDS,
        )
        return

    try:
        test = Test.objects.select_related("run__suite__project").get(pk=test_id)

        if test.processing_claim != claimed_processing:
            logger.warning(
                "process_test: stale/duplicate delivery for test %s (claimed token %s, current %s), skipping",
                test_id,
                claimed_processing,
                test.processing_claim,
                extra={
                    "test_id": test_id,
                    "claimed_processing": claimed_processing,
                    "current_processing_claim": test.processing_claim,
                },
            )
            return

        if test.status in (Test.STATUS_DONE, Test.STATUS_FAILED):
            logger.warning(
                "process_test: test %s (claim %s) already reached terminal status %s, skipping duplicate delivery",
                test_id,
                claimed_processing,
                test.status,
                extra={
                    "test_id": test_id,
                    "claimed_processing": claimed_processing,
                    "status": test.status,
                },
            )
            return

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
            pipeline_failed = False
        except Exception:
            logger.exception("process_test failed", extra={"test_id": test_id})
            pipeline_failed = True

        test.refresh_from_db()

        if test.processing_claim != claimed_processing:
            logger.warning(
                "process_test: test %s claim superseded while processing (was %s, now %s); "
                "discarding this result without writing status or deleting the staged upload",
                test_id,
                claimed_processing,
                test.processing_claim,
                extra={
                    "test_id": test_id,
                    "claimed_processing": claimed_processing,
                    "current_processing_claim": test.processing_claim,
                },
            )
            return

        if pipeline_failed:
            test.status = Test.STATUS_FAILED
            test.save(update_fields=["status"])
        else:
            test.is_new_baseline = is_new_baseline
            test.status = Test.STATUS_DONE
            test.save(update_fields=["status", "is_new_baseline"])

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
