import threading
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from django.conf import settings as django_settings
from django.db import connection
from django.db.models import F

from core.models import Test
from core.tasks import (
    _LOCK_WAIT_COUNTDOWN_SECONDS,
    _MAX_LOCK_WAIT_REQUEUES,
    _PROCESS_TEST_LOCK_NAMESPACE,
    delete_test_file_keys,
    process_test,
)

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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE
        assert test.process_attempts == 1

    def test_attempt_at_cap_still_processes_normally(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.PROCESS_TEST_MAX_ATTEMPTS = 3
        test = test_factory(process_attempts=settings.PROCESS_TEST_MAX_ATTEMPTS - 1)

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file"),
        ):
            mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
            mock_instance = MagicMock()
            mock_instance.run.return_value = False
            mock_cls.return_value = mock_instance

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

            mock_cls.assert_called_once()
            mock_download.assert_called_once()

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE
        assert test.process_attempts == settings.PROCESS_TEST_MAX_ATTEMPTS

    def test_attempt_over_cap_bails_to_failed_without_reprocessing(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.PROCESS_TEST_MAX_ATTEMPTS = 3
        starting_attempts = settings.PROCESS_TEST_MAX_ATTEMPTS
        test = test_factory(process_attempts=starting_attempts)

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file") as mock_delete,
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

            mock_cls.assert_not_called()
            mock_download.assert_not_called()
            mock_delete.assert_called_once()

        test.refresh_from_db()
        assert test.status == Test.STATUS_FAILED
        assert test.process_attempts == starting_attempts + 1

    def test_releases_lock_when_bailing_over_cap(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.PROCESS_TEST_MAX_ATTEMPTS = 3
        test = test_factory(process_attempts=settings.PROCESS_TEST_MAX_ATTEMPTS)

        with (
            patch("core.tasks.ScreenshotComparison"),
            patch("core.tasks._download_staged_file"),
            patch("core.tasks._delete_staged_file"),
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        # See test_releases_lock_after_successful_run for why pg_advisory_unlock
        # (returning False) is the correct check here, not pg_try_advisory_lock.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
            assert cursor.fetchone()[0] is False

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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        test.refresh_from_db()
        assert test.status == Test.STATUS_FAILED

    def test_attempt_counter_survives_normal_pipeline_failure(self, test_factory, settings):
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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        test.refresh_from_db()
        assert test.status == Test.STATUS_FAILED
        assert test.process_attempts == 1

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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        assert Test.STATUS_PROCESSING in statuses_seen

    def test_releases_lock_after_successful_run(self, test_factory, settings):
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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        # pg_advisory_unlock returns False when the calling session holds no such
        # lock. Calling it directly (with no preceding pg_try_advisory_lock) lets us
        # actually distinguish "process_test released its lock" from "it leaked it" —
        # pg_try_advisory_lock is re-entrant within a session, so checking via that
        # would always succeed regardless of whether process_test's own unlock ran.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
            assert cursor.fetchone()[0] is False

    def test_held_lock_blocks_concurrent_invocation_and_requeues(self, test_factory, settings):
        # Postgres session-level advisory locks are re-entrant within the SAME
        # session, and CELERY_TASK_ALWAYS_EAGER runs process_test synchronously
        # on this test's own DB connection/session. So acquiring the lock via
        # `connection.cursor()` here (as the brief's literal snippet does) and
        # then calling process_test.delay(...) would just re-acquire the lock
        # from the same session and succeed, not reproduce the "another
        # invocation is already processing this test_id" scenario.
        #
        # To genuinely simulate a concurrent invocation (a different worker /
        # DB session), hold the lock from a separate thread with its own
        # connection, matching how two real Celery workers would race.
        #
        # `process_test.apply_async` is mocked below so the lock-busy path's
        # requeue call is observable instead of actually recursing. This
        # test's job is to verify a SINGLE contended invocation's behavior
        # (it never touches the row and requeues itself exactly once with
        # the expected args), not the full requeue-and-give-up loop (see
        # test_lock_contention_gives_up_after_cap for that).
        test = test_factory()
        original_status = test.status

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_lock_in_other_session():
            # `connection` (the module-level django.db.connection imported at the top
            # of this file) is thread-local by Django's own connection-handling
            # machinery, so using it here naturally gets a separate session/backend
            # connection from the one the main thread uses.
            try:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                        assert cursor.fetchone()[0] is True
                    lock_acquired.set()
                    release_lock.wait()
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                except BaseException as exc:  # noqa: BLE001 - surfaced to main thread below
                    holder_errors.append(exc)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_lock_in_other_session)
        holder.start()

        try:
            assert lock_acquired.wait(timeout=5)

            with (
                patch("core.tasks.ScreenshotComparison") as mock_cls,
                patch("core.tasks._download_staged_file") as mock_download,
                patch("core.tasks._delete_staged_file"),
                patch("core.tasks.process_test.apply_async") as mock_apply_async,
            ):
                # See the comment in test_lock_contention_requeues_instead_of_dropping_message
                # for why this calls the task directly instead of .delay()/.apply_async()
                # now that apply_async is mocked.
                process_test(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

                mock_cls.assert_not_called()
                mock_download.assert_not_called()
                mock_apply_async.assert_called_once_with(
                    args=[test.id, "screenshots/staging/1/upload.png", test.processing_claim, 1],
                    countdown=_LOCK_WAIT_COUNTDOWN_SECONDS,
                )

            test.refresh_from_db()
            assert test.status == original_status
        finally:
            release_lock.set()
            holder.join(timeout=5)
            assert not holder.is_alive()

        if holder_errors:
            raise holder_errors[0]

    def test_releases_lock_after_failed_run(self, test_factory, settings):
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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

        test.refresh_from_db()
        assert test.status == Test.STATUS_FAILED

        # See test_releases_lock_after_successful_run for why pg_advisory_unlock
        # (returning False) is the correct check here, not pg_try_advisory_lock.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
            assert cursor.fetchone()[0] is False

    def test_releases_lock_when_test_lookup_raises(self, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True
        bogus_id = 999_999_999

        with pytest.raises(Test.DoesNotExist):
            process_test.delay(bogus_id, "screenshots/staging/1/upload.png", 0)

        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, bogus_id])
            assert cursor.fetchone()[0] is False

    def test_stale_claim_is_rejected_without_touching_anything(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()
        original_status = test.status

        # Simulate a newer claim having since superseded this delivery: the row's
        # CURRENT processing_claim is now 5, but this delivery still carries the
        # OLD token (1) it was enqueued with.
        test.processing_claim = 5
        test.save(update_fields=["processing_claim"])

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file") as mock_delete,
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", 1)

            mock_cls.assert_not_called()
            mock_download.assert_not_called()
            mock_delete.assert_not_called()

        test.refresh_from_db()
        assert test.status == original_status
        assert test.process_attempts == 0

    def test_matching_claim_proceeds_normally(self, test_factory, settings):
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

            process_test.delay(test.id, "screenshots/staging/1/upload.png", 0)

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE
        assert test.process_attempts == 1

    def test_releases_lock_on_stale_claim_bail(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()
        test.processing_claim = 5
        test.save(update_fields=["processing_claim"])

        with (
            patch("core.tasks.ScreenshotComparison"),
            patch("core.tasks._download_staged_file"),
            patch("core.tasks._delete_staged_file"),
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", 1)

        # See test_releases_lock_after_successful_run for why pg_advisory_unlock
        # (returning False) is the correct check here, not pg_try_advisory_lock.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
            assert cursor.fetchone()[0] is False

    def test_duplicate_delivery_of_done_claim_is_rejected_without_touching_anything(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory(status=Test.STATUS_DONE, process_attempts=1, processing_claim=0)

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file") as mock_delete,
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", 0)

            mock_cls.assert_not_called()
            mock_download.assert_not_called()
            mock_delete.assert_not_called()

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE
        assert test.process_attempts == 1

    def test_duplicate_delivery_of_failed_claim_is_rejected_without_touching_anything(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory(status=Test.STATUS_FAILED, process_attempts=1, processing_claim=0)

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file") as mock_delete,
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", 0)

            mock_cls.assert_not_called()
            mock_download.assert_not_called()
            mock_delete.assert_not_called()

        test.refresh_from_db()
        assert test.status == Test.STATUS_FAILED
        assert test.process_attempts == 1

    def test_releases_lock_on_terminal_status_duplicate_delivery_bail(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory(status=Test.STATUS_DONE, process_attempts=1, processing_claim=0)

        with (
            patch("core.tasks.ScreenshotComparison"),
            patch("core.tasks._download_staged_file"),
            patch("core.tasks._delete_staged_file"),
        ):
            process_test.delay(test.id, "screenshots/staging/1/upload.png", 0)

        # See test_releases_lock_after_successful_run for why pg_advisory_unlock
        # (returning False) is the correct check here, not pg_try_advisory_lock.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
            assert cursor.fetchone()[0] is False

    def test_crash_retry_from_processing_status_still_proceeds_normally(self, test_factory, settings):
        # Sanity check: a genuine crash-retry redelivery leaves status at
        # STATUS_PROCESSING (committed before the risky pipeline work, per the
        # comment above), never STATUS_DONE/STATUS_FAILED. The new terminal-status
        # check must only block DONE/FAILED, not PROCESSING (or PENDING).
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory(status=Test.STATUS_PROCESSING, process_attempts=1, processing_claim=0)

        with (
            patch("core.tasks.ScreenshotComparison") as mock_cls,
            patch("core.tasks._download_staged_file") as mock_download,
            patch("core.tasks._delete_staged_file"),
        ):
            mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
            mock_instance = MagicMock()
            mock_instance.run.return_value = False
            mock_cls.return_value = mock_instance

            process_test.delay(test.id, "screenshots/staging/1/upload.png", 0)

            mock_cls.assert_called_once()
            mock_download.assert_called_once()

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE
        assert test.process_attempts == 2

    def test_lock_contention_requeues_instead_of_dropping_message(self, test_factory, settings):
        # Same "hold the lock from a separate thread/session" pattern as
        # test_held_lock_blocks_concurrent_invocation above.
        test = test_factory()

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_lock_in_other_session():
            try:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                        assert cursor.fetchone()[0] is True
                    lock_acquired.set()
                    release_lock.wait()
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                except BaseException as exc:  # noqa: BLE001 - surfaced to main thread below
                    holder_errors.append(exc)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_lock_in_other_session)
        holder.start()

        try:
            assert lock_acquired.wait(timeout=5)

            with (
                patch("core.tasks.ScreenshotComparison") as mock_cls,
                patch("core.tasks._download_staged_file") as mock_download,
                patch("core.tasks._delete_staged_file"),
                patch("core.tasks.process_test.apply_async") as mock_apply_async,
            ):
                # Call the task directly (not .delay()/.apply_async()) here: those
                # both resolve to the SAME `apply_async` attribute we're patching
                # above (`.delay()` is literally `return self.apply_async(...)`),
                # so going through them would swallow this outer invocation into
                # the mock too and the body below would never actually run.
                # Calling the task instance directly invokes Task.__call__, which
                # runs the underlying function body synchronously without touching
                # apply_async at all — leaving the mock free to observe only the
                # INNER, explicit requeue call the function makes on lock contention.
                process_test(test.id, "screenshots/staging/1/upload.png", test.processing_claim)

                mock_cls.assert_not_called()
                mock_download.assert_not_called()
                mock_apply_async.assert_called_once_with(
                    args=[test.id, "screenshots/staging/1/upload.png", test.processing_claim, 1],
                    countdown=_LOCK_WAIT_COUNTDOWN_SECONDS,
                )
        finally:
            release_lock.set()
            holder.join(timeout=5)
            assert not holder.is_alive()

        if holder_errors:
            raise holder_errors[0]

    def test_lock_contention_gives_up_after_cap(self, test_factory, settings):
        test = test_factory()

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_lock_in_other_session():
            try:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                        assert cursor.fetchone()[0] is True
                    lock_acquired.set()
                    release_lock.wait()
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                except BaseException as exc:  # noqa: BLE001 - surfaced to main thread below
                    holder_errors.append(exc)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_lock_in_other_session)
        holder.start()

        try:
            assert lock_acquired.wait(timeout=5)

            with (
                patch("core.tasks.ScreenshotComparison") as mock_cls,
                patch("core.tasks._download_staged_file") as mock_download,
                patch("core.tasks._delete_staged_file"),
                patch("core.tasks.process_test.apply_async") as mock_apply_async,
            ):
                # See the comment in test_lock_contention_requeues_instead_of_dropping_message
                # for why this calls the task directly instead of .delay()/.apply_async().
                process_test(
                    test.id,
                    "screenshots/staging/1/upload.png",
                    test.processing_claim,
                    _MAX_LOCK_WAIT_REQUEUES,
                )

                mock_cls.assert_not_called()
                mock_download.assert_not_called()
                mock_apply_async.assert_not_called()
        finally:
            release_lock.set()
            holder.join(timeout=5)
            assert not holder.is_alive()

        if holder_errors:
            raise holder_errors[0]

    def test_requeued_invocation_eventually_completes_after_lock_clears(self, test_factory, settings):
        # Proves the other half of the requeue fix: a contended invocation
        # isn't just retried with the right args (already covered by
        # test_lock_contention_requeues_instead_of_dropping_message above) —
        # once the lock it was waiting on actually clears, the requeued
        # invocation goes on to complete the pipeline and reach STATUS_DONE,
        # i.e. the restart is not permanently lost.
        test = test_factory()
        staging_key = "screenshots/staging/1/upload.png"

        lock_acquired = threading.Event()
        release_lock = threading.Event()
        lock_released = threading.Event()
        holder_errors: list[BaseException] = []

        def hold_lock_in_other_session():
            try:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                        assert cursor.fetchone()[0] is True
                    lock_acquired.set()
                    release_lock.wait(timeout=5)
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [_PROCESS_TEST_LOCK_NAMESPACE, test.id])
                    lock_released.set()
                except BaseException as exc:  # noqa: BLE001 - surfaced to main thread below
                    holder_errors.append(exc)
            finally:
                connection.close()

        holder = threading.Thread(target=hold_lock_in_other_session)
        holder.start()

        try:
            assert lock_acquired.wait(timeout=5)

            with (
                patch("core.tasks.ScreenshotComparison") as mock_cls,
                patch("core.tasks._download_staged_file") as mock_download,
                patch("core.tasks._delete_staged_file"),
                patch("core.tasks.process_test.apply_async") as mock_apply_async,
            ):
                mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
                mock_instance = MagicMock()
                mock_instance.run.return_value = False
                mock_cls.return_value = mock_instance

                def requeue_after_lock_clears(*, args, countdown):
                    # Release the held lock and wait for the holder to
                    # actually relinquish it (not just signal it to) before
                    # re-invoking — otherwise this would race the holder's
                    # own unlock instead of genuinely waiting for the lock
                    # to clear.
                    release_lock.set()
                    assert lock_released.wait(timeout=5)
                    process_test(*args)

                mock_apply_async.side_effect = requeue_after_lock_clears

                # See the comment in test_lock_contention_requeues_instead_of_dropping_message
                # for why this calls the task directly instead of .delay()/.apply_async().
                process_test(test.id, staging_key, test.processing_claim, 0)

                mock_apply_async.assert_called_once_with(
                    args=[test.id, staging_key, test.processing_claim, 1],
                    countdown=_LOCK_WAIT_COUNTDOWN_SECONDS,
                )
        finally:
            holder.join(timeout=5)
            assert not holder.is_alive()

        if holder_errors:
            raise holder_errors[0]

        test.refresh_from_db()
        assert test.status == Test.STATUS_DONE

    @pytest.mark.django_db(transaction=True)
    def test_mid_flight_supersede_discards_stale_result_without_writing_or_deleting(self, test_factory, settings):
        # transaction=True: the pipeline thread below runs process_test on its OWN
        # DB connection/session (same reasoning as
        # test_held_lock_blocks_concurrent_invocation_and_requeues), so the Test
        # row created here must be actually committed, not left inside
        # the default per-test SAVEPOINT, or that thread's session won't see it.
        #
        # The core regression this task fixes: invocation A acquires the lock and
        # passes its initial claim check, then while A is still mid-pipeline an
        # admin restart bumps processing_claim (simulating restart_processing's
        # atomic .update()). A must finish without writing status/is_new_baseline
        # and without deleting the staged upload B's restart still needs.
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()
        original_status = test.status
        staging_key = "screenshots/staging/1/upload.png"

        entered_pipeline = threading.Event()
        resume_pipeline = threading.Event()
        task_errors: list[BaseException] = []

        def fake_run(*_args, **_kwargs):
            entered_pipeline.set()
            resume_pipeline.wait(timeout=5)
            return False

        def run_task_in_background():
            try:
                with (
                    patch("core.tasks.ScreenshotComparison") as mock_cls,
                    patch("core.tasks._download_staged_file") as mock_download,
                    patch("core.tasks._delete_staged_file") as mock_delete,
                ):
                    mock_download.side_effect = lambda key, dest: dest.write_bytes(b"fakepng")
                    mock_instance = MagicMock()
                    mock_instance.run.side_effect = fake_run
                    mock_cls.return_value = mock_instance

                    process_test.delay(test.id, staging_key, test.processing_claim)

                    # Assert inside the same patch context, but capture failures
                    # instead of letting a bare assert hang/kill this thread silently.
                    try:
                        mock_delete.assert_not_called()
                    except AssertionError as exc:
                        task_errors.append(exc)
            except BaseException as exc:  # noqa: BLE001 - surfaced to main thread below
                task_errors.append(exc)
            finally:
                connection.close()

        worker = threading.Thread(target=run_task_in_background)
        worker.start()

        try:
            assert entered_pipeline.wait(timeout=5)

            # Simulate a concurrent admin restart bumping the fencing token while
            # the stale invocation is still inside ScreenshotComparison.run().
            Test.objects.filter(pk=test.id).update(processing_claim=F("processing_claim") + 1)
        finally:
            resume_pipeline.set()
            worker.join(timeout=5)
            assert not worker.is_alive()

        if task_errors:
            raise task_errors[0]

        test.refresh_from_db()
        # process_test unconditionally (and correctly, per its pre-existing
        # process_attempts-cap mechanism) commits STATUS_PROCESSING before the
        # pipeline runs, so it's already past `original_status` (STATUS_PENDING)
        # by the time the claim gets superseded mid-flight below. What this fix
        # guards is the TERMINAL write that happens after the pipeline finishes:
        # it must never land as STATUS_DONE for a superseded claim.
        assert original_status == Test.STATUS_PENDING
        assert test.status == Test.STATUS_PROCESSING
        assert test.status != Test.STATUS_DONE
        assert test.processing_claim == 1

        # No lock-release check here: the lock was acquired by the WORKER
        # thread's own DB session (via process_test.delay(...) running under
        # CELERY_TASK_ALWAYS_EAGER on that thread's connection), and Postgres
        # session advisory locks cannot be released from a different session
        # by definition — asserting via this (main-thread) connection would
        # unconditionally return False regardless of whether process_test's
        # own unlock ran correctly, proving nothing. The ordinary release path
        # is already covered by test_releases_lock_after_successful_run et al;
        # this test's job is the claim/status/file-deletion guard above.


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

        record = next(r for r in caplog.records if r.message == "Failed to delete some test files")
        assert record.errors == [{"Key": "screenshots/1/baseline.png", "Code": "AccessDenied", "Message": "nope"}]

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

    def test_logs_but_does_not_raise_on_connection_error(self, settings, caplog):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        keys = ["screenshots/1/original.png"]

        with patch("core.tasks.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.delete_objects.side_effect = EndpointConnectionError(endpoint_url="https://s3.example.com")
            mock_get_client.return_value = mock_client

            delete_test_file_keys.delay(keys)  # must not raise
