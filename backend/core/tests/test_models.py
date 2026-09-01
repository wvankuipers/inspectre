"""Model-layer invariants. Pinning these here means a model regression fails
upstream of any view, serializer, or service test (which would all fail too,
but with more confusing diagnostics).
"""

from unittest.mock import MagicMock, patch

import pytest
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import IntegrityError, connection, transaction

from core.models import Baseline, Run, Suite, Test

pytestmark = pytest.mark.django_db


# =============================================================================
# Slug auto-update on rename
# =============================================================================


class TestSlugAutoUpdate:
    """decisions.md #4: rename re-slugs the model. Old links break, future Test
    keys reflect the new slug, existing baselines orphan.
    """

    def test_project_slug_set_from_name_on_create(self, project_factory):
        project = project_factory(name="Acme Site")
        assert project.slug == "acme-site"

    def test_project_slug_updates_on_rename(self, project_factory):
        project = project_factory(name="Acme Site")
        project.name = "Acme Inc"
        project.save()
        project.refresh_from_db()
        assert project.slug == "acme-inc"

    def test_suite_slug_set_from_name_on_create(self, suite_factory):
        suite = suite_factory(name="Mobile Phones")
        assert suite.slug == "mobile-phones"

    def test_suite_slug_updates_on_rename(self, suite_factory):
        suite = suite_factory(name="Mobile")
        suite.name = "Tablet"
        suite.save()
        suite.refresh_from_db()
        assert suite.slug == "tablet"

    def test_two_suites_in_different_projects_can_share_a_slug(
        self,
        project_factory,
        suite_factory,
    ):
        """Suite slug is unique PER PROJECT, not globally — fixes a quiet legacy bug."""
        a = project_factory(name="Project A")
        b = project_factory(name="Project B")
        suite_factory(project=a, name="Desktop")
        suite_factory(project=b, name="Desktop")
        assert Suite.objects.filter(slug="desktop").count() == 2

    def test_two_suites_in_same_project_cannot_share_a_slug(
        self,
        project_factory,
        suite_factory,
    ):
        """The unique_suite_slug_per_project constraint must reject duplicates."""
        project = project_factory(name="Acme")
        suite_factory(project=project, name="Desktop")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                suite_factory(project=project, name="Desktop")

    def test_project_slug_is_globally_unique(self, project_factory):
        """Stricter than legacy: two names that slugify the same raise IntegrityError."""
        project_factory(name="Acme Inc")

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                project_factory(name="Acme  Inc")  # extra space → same slug


# =============================================================================
# Test.key formula
# =============================================================================


class TestKeyFormula:
    """data-model.md, "Key formula": tests are linked to baselines by a slugified
    concatenation of project, suite, name, browser, size.
    """

    def test_key_combines_all_five_inputs(
        self,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        project = project_factory(name="Acme Site")
        suite = suite_factory(project=project, name="Desktop")
        run = run_factory(suite=suite)
        test = test_factory(run=run, name="Homepage", browser="Chrome", size="1024")

        assert test.key == "acme-site-desktop-homepage-chrome-1024"

    def test_key_recomputes_on_re_save_after_rename(
        self,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        """decisions.md #4: future Tests get new keys; existing rows refresh on next save."""
        project = project_factory(name="Acme")
        suite = suite_factory(project=project, name="Desktop")
        run = run_factory(suite=suite)
        test = test_factory(run=run, name="Homepage", browser="Chrome", size="1024")
        original_key = test.key

        project.name = "Acme Inc"
        project.save()

        test.save()
        test.refresh_from_db()
        assert test.key != original_key
        assert test.key.startswith("acme-inc-")

    @pytest.mark.parametrize(
        "inputs,expected",
        [
            # (project, suite, name, browser, size) → key
            (("Acme", "Desktop", "Homepage", "Chrome", "1024"), "acme-desktop-homepage-chrome-1024"),
            (("Acme X", "Desk", "Home page", "Chrome", "1024"), "acme-x-desk-home-page-chrome-1024"),
            (("Café", "Desk", "Login", "Chrome", "1024"), "cafe-desk-login-chrome-1024"),
            (("Acme!", "Desk", "Page/X", "Chrome", "1024"), "acme-desk-pagex-chrome-1024"),
        ],
    )
    def test_key_handles_punctuation_and_whitespace(
        self,
        inputs,
        expected,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        """slugify() collapses whitespace, lowercases, drops punctuation, ASCII-folds."""
        proj_name, suite_name, name, browser, size = inputs
        project = project_factory(name=proj_name)
        suite = suite_factory(project=project, name=suite_name)
        run = run_factory(suite=suite)
        test = test_factory(run=run, name=name, browser=browser, size=size)
        assert test.key == expected


# =============================================================================
# Run sequential_id
# =============================================================================


class TestRunSequentialId:
    def test_first_run_in_suite_starts_at_1(self, suite_factory, run_factory):
        suite = suite_factory()
        run = run_factory(suite=suite)
        assert run.sequential_id == 1

    def test_sequential_ids_increment_per_suite(self, suite_factory, run_factory):
        suite = suite_factory()
        seqs = [run_factory(suite=suite).sequential_id for _ in range(5)]
        assert seqs == [1, 2, 3, 4, 5]

    def test_different_suites_have_independent_counters(self, suite_factory, run_factory):
        a = suite_factory()
        b = suite_factory()
        run_factory(suite=a)
        run_factory(suite=a)
        first_b = run_factory(suite=b)
        assert first_b.sequential_id == 1

    def test_counter_does_not_resequence_after_delete(
        self,
        suite_factory,
        run_factory,
        settings,
    ):
        """Legacy parity: the counter is monotonic. Deleting run #1 leaves the
        next-run counter at 3, not 2 — the SPA's URL bar shows #1 missing.
        """
        # Disable retention so deletes don't trigger re-purges.
        settings.RUN_RETENTION_PER_SUITE = 100

        suite = suite_factory()
        first = run_factory(suite=suite)
        run_factory(suite=suite)

        first.delete()

        third = run_factory(suite=suite)
        assert third.sequential_id == 3  # not 2


# =============================================================================
# Race condition — concurrent inserts under select_for_update
# =============================================================================


@pytest.mark.skipif(
    "sqlite" in str(connection.settings_dict.get("ENGINE", "")),
    reason="select_for_update is a no-op on SQLite — would pass for the wrong reason",
)
class TestRunSequentialIdRace:
    """data-model.md, "Per-suite sequential id": Run.save() must use
    select_for_update on the Suite row to keep the counter race-safe.

    Runs against real Postgres — the actual locking mechanism we depend on.
    """

    @pytest.mark.slow
    def test_concurrent_inserts_produce_distinct_ids(self, suite_factory, transactional_db):
        import threading

        suite = suite_factory()
        results = []
        errors = []

        def worker():
            try:
                run = Run.objects.create(suite=suite)
                results.append(run.sequential_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                connection.close()

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"worker errors: {errors}"
        assert sorted(results) == [1, 2, 3, 4, 5], f"sequential_id collision under concurrency: got {sorted(results)}"


# =============================================================================
# purge_old_runs signal — keeps N most recent, cascades, fires only on create
# =============================================================================


class TestPurgeOldRuns:
    """signals.py: post_save on Run, gated on created=True. Keeps
    settings.RUN_RETENTION_PER_SUITE most recent runs per suite.
    """

    def test_keeps_default_five_runs(self, suite_factory, run_factory, settings):
        settings.RUN_RETENTION_PER_SUITE = 5
        suite = suite_factory()
        for _ in range(8):
            run_factory(suite=suite)
        assert Run.objects.filter(suite=suite).count() == 5

    def test_keeps_the_most_recent(self, suite_factory, run_factory, settings):
        settings.RUN_RETENTION_PER_SUITE = 5
        suite = suite_factory()
        for _ in range(8):
            run_factory(suite=suite)
        seqs = list(Run.objects.filter(suite=suite).order_by("sequential_id").values_list("sequential_id", flat=True))
        assert seqs == [4, 5, 6, 7, 8]  # 1, 2, 3 purged

    def test_purge_cascades_to_tests(
        self,
        suite_factory,
        run_factory,
        test_factory,
        settings,
    ):
        settings.RUN_RETENTION_PER_SUITE = 1
        suite = suite_factory()
        run_a = run_factory(suite=suite)
        test_factory(run=run_a, name="will-be-purged")
        run_factory(suite=suite)  # triggers the purge

        assert not Run.objects.filter(pk=run_a.pk).exists()
        assert not Test.objects.filter(name="will-be-purged").exists()

    def test_retention_setting_is_honoured(
        self,
        suite_factory,
        run_factory,
        settings,
    ):
        settings.RUN_RETENTION_PER_SUITE = 3
        suite = suite_factory()
        for _ in range(5):
            run_factory(suite=suite)
        assert Run.objects.filter(suite=suite).count() == 3

    def test_purge_does_not_cross_suite_boundaries(
        self,
        suite_factory,
        run_factory,
        settings,
    ):
        settings.RUN_RETENTION_PER_SUITE = 1
        a = suite_factory()
        b = suite_factory()
        run_factory(suite=b)  # the only run in b — should survive
        for _ in range(3):
            run_factory(suite=a)

        assert Run.objects.filter(suite=a).count() == 1
        assert Run.objects.filter(suite=b).count() == 1  # untouched

    def test_purge_deletes_test_files_from_storage(
        self,
        suite_factory,
        run_factory,
        test_factory,
        settings,
        django_capture_on_commit_callbacks,
    ):
        """S3 keys on purged Tests must be sent to the delete task, not just the DB rows.

        File deletion is now enqueued as an async Celery task from the
        pre_delete signal, deferred to transaction.on_commit, and that task
        deletes via a raw boto3 S3 client rather than Django's storage API —
        so it never touches the FileSystemStorage the test suite swaps in for
        hermetic tests. Asserting `storage.exists()` is no longer meaningful;
        instead assert the S3 client was actually called with the file's key.
        Wrapping the purge in django_capture_on_commit_callbacks(execute=True)
        runs the on_commit callback inline (CELERY_TASK_ALWAYS_EAGER makes the
        task itself synchronous) so this test can assert on the call.
        """
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.RUN_RETENTION_PER_SUITE = 1
        suite = suite_factory()
        run_a = run_factory(suite=suite)
        test = test_factory(run=run_a)
        test.screenshot.save("original.png", ContentFile(b"fake-png"), save=True)
        storage_name = test.screenshot.name

        with patch("core.tasks.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            with django_capture_on_commit_callbacks(execute=True):
                run_factory(suite=suite)  # triggers the purge

        mock_client.delete_objects.assert_called_once()
        _, kwargs = mock_client.delete_objects.call_args
        assert kwargs["Delete"]["Objects"] == [{"Key": storage_name}]

    def test_signal_only_fires_on_create(
        self,
        suite_factory,
        run_factory,
        settings,
    ):
        """Updating a Run shouldn't trigger purge — signal is gated on created=True."""
        settings.RUN_RETENTION_PER_SUITE = 5
        suite = suite_factory()
        runs = [run_factory(suite=suite) for _ in range(5)]

        # Touch the most recent run; if the signal fired on update, count would drop.
        runs[-1].save()

        assert Run.objects.filter(suite=suite).count() == 5


# =============================================================================
# delete_test_files signal — pre_delete on Test enqueues async S3 cleanup
# instead of deleting synchronously in the request.
# =============================================================================


class TestDeleteTestFilesSignal:
    def test_enqueues_delete_task_with_non_empty_field_keys_only(
        self, test_factory, settings, django_capture_on_commit_callbacks
    ):
        from core.models import Test

        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()
        test.screenshot.save("original.png", ContentFile(b"fake"), save=False)
        test.screenshot_diff.save("diff.png", ContentFile(b"fake"), save=False)
        test.save()
        screenshot_name = test.screenshot.name
        diff_name = test.screenshot_diff.name

        with patch("core.signals.delete_test_file_keys") as mock_task:
            with django_capture_on_commit_callbacks(execute=True):
                test.delete()

        assert not Test.objects.filter(pk=test.pk).exists()
        mock_task.delay.assert_called_once()
        (called_keys,), _ = mock_task.delay.call_args
        assert sorted(called_keys) == sorted([screenshot_name, diff_name])

    def test_does_not_enqueue_when_no_files_attached(self, test_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()

        with patch("core.signals.delete_test_file_keys") as mock_task:
            test.delete()

        mock_task.delay.assert_not_called()

    def test_enqueue_waits_for_transaction_commit(self, test_factory, settings, transactional_db):
        """The task must not fire while the delete is still inside an open
        transaction that could roll back."""
        from django.db import transaction

        settings.CELERY_TASK_ALWAYS_EAGER = True
        test = test_factory()
        test.screenshot.save("original.png", ContentFile(b"fake"), save=False)
        test.save()

        with patch("core.signals.delete_test_file_keys") as mock_task:
            with transaction.atomic():
                test.delete()
                mock_task.delay.assert_not_called()
            mock_task.delay.assert_called_once()

        # A rolled-back transaction never commits, so the on_commit callback
        # must never fire either.
        test = test_factory()
        test.screenshot.save("original.png", ContentFile(b"fake"), save=False)
        test.save()

        with patch("core.signals.delete_test_file_keys") as mock_task:
            with transaction.atomic():
                test.delete()
                transaction.set_rollback(True)
            mock_task.delay.assert_not_called()


# =============================================================================
# Cascade behaviour — on_delete declarations
# =============================================================================


class TestCascades:
    def test_deleting_project_removes_suites_runs_tests(
        self,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
        settings,
    ):
        # Disable purge so the Test we create stays around long enough for
        # the cascade test to be meaningful.
        settings.RUN_RETENTION_PER_SUITE = 100

        project = project_factory()
        suite = suite_factory(project=project)
        run = run_factory(suite=suite)
        test_factory(run=run)

        project.delete()

        assert Suite.objects.count() == 0
        assert Run.objects.count() == 0
        assert Test.objects.count() == 0

    def test_deleting_suite_removes_baselines(self, suite_factory, baseline_factory):
        suite = suite_factory()
        baseline_factory(suite=suite)
        suite.delete()
        assert Baseline.objects.count() == 0

    def test_deleting_test_does_not_delete_baseline(
        self,
        suite_factory,
        baseline_factory,
        test_factory,
    ):
        """Baseline.test = on_delete=SET_NULL: deleting the originating Test
        leaves the Baseline intact (the screenshot is still valid).
        """
        suite = suite_factory()
        test = test_factory()
        baseline = baseline_factory(suite=suite, test=test)

        test.delete()
        baseline.refresh_from_db()
        assert baseline.test_id is None


# =============================================================================
# Test status and is_new_baseline fields
# =============================================================================


class TestTestStatusField:
    def test_new_test_has_pending_status(self, test_factory):
        test = test_factory()
        assert test.status == "pending"

    def test_invalid_status_is_rejected(self, test_factory):
        test = test_factory()
        test.status = "invalid"
        with pytest.raises(ValidationError):
            test.full_clean()

    def test_is_new_baseline_defaults_to_none(self, test_factory):
        test = test_factory()
        assert test.is_new_baseline is None

    def test_is_new_baseline_can_be_set_to_true(self, test_factory):
        test = test_factory()
        test.is_new_baseline = True
        test.save()
        test.refresh_from_db()
        assert test.is_new_baseline is True

    def test_test_status_has_composite_index_with_created_at(self):
        """ProcessingQueueAdmin filters on status and orders by created_at — both
        columns must be covered by one index so that query doesn't full-scan as
        the Test table grows."""
        index_fields = [tuple(idx.fields) for idx in Test._meta.indexes]
        assert ("status", "created_at") in index_fields
