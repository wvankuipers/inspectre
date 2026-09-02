from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError
from django.conf import settings as django_settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models import Test
from core.services.s3 import staging_key_for_test

pytestmark = pytest.mark.django_db


User = get_user_model()


# =============================================================================
# Auth gate — /admin/ requires login, /api/ and / do not
# =============================================================================


class TestAdminAuth:
    def test_admin_index_redirects_anonymous_to_login(self, client):
        response = client.get("/admin/")
        # Django's stock behaviour: 302 to /admin/login/?next=/admin/
        assert response.status_code == 302
        assert "/admin/login/" in response.headers["Location"]

    def test_admin_index_loads_for_staff_user(self, client):
        User.objects.create_user(
            username="admin",
            password="supersecret",
            is_staff=True,
            is_superuser=True,
        )
        client.login(username="admin", password="supersecret")

        response = client.get("/admin/")
        assert response.status_code == 200
        assert b"Site administration" in response.content

    def test_non_staff_user_cannot_access_admin(self, client):
        User.objects.create_user(username="regular", password="regular", is_staff=False)
        client.login(username="regular", password="regular")

        response = client.get("/admin/")
        # Django treats is_staff=False as if the user weren't logged in for /admin/.
        assert response.status_code == 302
        assert "/admin/login/" in response.headers["Location"]

    def test_api_endpoints_are_anonymous(self, client):
        """The auth gate must NOT extend to /api/. decisions.md, "Auth (public / API)"."""
        # Empty 200 (no projects), not 401 or 302.
        assert client.get("/api/projects/").status_code == 200

    def test_legacy_endpoints_are_anonymous(self, client):
        """Same invariant for the legacy API surface."""
        response = client.post("/runs", {"project": "P", "suite": "S"})
        assert response.status_code == 200


# =============================================================================
# CRUD reachability — every model has its admin pages and they don't crash
# =============================================================================


class TestAdminCrud:
    """Smoke tests: every ModelAdmin's listing renders for a logged-in admin."""

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username="admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        client.login(username="admin", password="secret")
        return client

    @pytest.mark.parametrize(
        "model_path",
        [
            "core/project",
            "core/suite",
            "core/run",
            "core/test",
            "core/baseline",
            "core/processingqueuetest",
        ],
    )
    def test_changelist_loads(self, admin_client, model_path):
        response = admin_client.get(f"/admin/{model_path}/")
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "model_path",
        [
            "core/project",
            "core/suite",
            # Run/Test/Baseline aren't realistically created from the admin form
            # (they need related objects + computed fields). Smoke-testing the add
            # page would mostly assert that the form renders, not that it works
            # end-to-end.
        ],
    )
    def test_add_page_loads(self, admin_client, model_path):
        response = admin_client.get(f"/admin/{model_path}/add/")
        assert response.status_code == 200

    def test_test_admin_changelist_shows_diff_pct_column(
        self,
        admin_client,
        test_factory,
    ):
        """The custom `diff_pct` method on TestAdmin renders without crashing."""
        test_factory(diff=12.34)
        response = admin_client.get("/admin/core/test/")
        assert response.status_code == 200
        assert b"12.34%" in response.content


# =============================================================================
# Rename-warning template — Project and Suite show the banner on edit
# =============================================================================


class TestRenameWarning:
    """The banner from RenameWarningMixin must:
    - appear on the change form (edit) for Project and Suite
    - NOT appear on the add form (no existing baselines to sever yet)
    - NOT appear on Run/Test/Baseline change forms (no rename concept).
    """

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username="admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        client.login(username="admin", password="secret")
        return client

    BANNER_PHRASE = b"Renaming severs baselines"

    def test_banner_visible_on_project_edit(self, admin_client, project_factory):
        project = project_factory()
        response = admin_client.get(f"/admin/core/project/{project.pk}/change/")
        assert response.status_code == 200
        assert self.BANNER_PHRASE in response.content

    def test_banner_visible_on_suite_edit(self, admin_client, suite_factory):
        suite = suite_factory()
        response = admin_client.get(f"/admin/core/suite/{suite.pk}/change/")
        assert response.status_code == 200
        assert self.BANNER_PHRASE in response.content

    def test_banner_absent_on_project_add(self, admin_client):
        response = admin_client.get("/admin/core/project/add/")
        assert response.status_code == 200
        assert self.BANNER_PHRASE not in response.content

    def test_banner_absent_on_suite_add(self, admin_client):
        response = admin_client.get("/admin/core/suite/add/")
        assert response.status_code == 200
        assert self.BANNER_PHRASE not in response.content

    @pytest.mark.parametrize(
        "admin_path",
        [
            "core/run",
            "core/test",
            "core/baseline",
        ],
    )
    def test_banner_absent_on_other_models(
        self,
        admin_client,
        admin_path,
        run_factory,
        test_factory,
        suite_factory,
        baseline_factory,
    ):
        """Run/Test/Baseline don't inherit the mixin — banner shouldn't appear."""
        if admin_path == "core/run":
            obj = run_factory()
        elif admin_path == "core/test":
            obj = test_factory()
        else:
            obj = baseline_factory(suite=suite_factory())

        response = admin_client.get(f"/admin/{admin_path}/{obj.pk}/change/")
        assert response.status_code == 200
        assert self.BANNER_PHRASE not in response.content


# =============================================================================
# ensure_admin_user — reconcile semantics
# =============================================================================


class TestEnsureAdminUser:
    """The management command bootstraps the single shared admin (admin.md)."""

    def test_creates_admin_when_missing(self, settings):
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "first-secret"

        call_command("ensure_admin_user")

        user = User.objects.get(username="admin")
        assert user.is_staff is True
        assert user.is_superuser is True
        assert user.check_password("first-secret")

    def test_updates_password_when_changed(self, settings):
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "first-secret"
        call_command("ensure_admin_user")

        # Operator rotates the password via env + redeploy.
        settings.ADMIN_PASSWORD = "second-secret"
        call_command("ensure_admin_user")

        user = User.objects.get(username="admin")
        assert user.check_password("second-secret")
        assert not user.check_password("first-secret")

    def test_does_not_rehash_when_password_unchanged(self, settings):
        """check_password short-circuits; set_password is NOT called on a no-op run."""
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "unchanged"
        call_command("ensure_admin_user")

        hash_before = User.objects.get(username="admin").password
        call_command("ensure_admin_user")
        hash_after = User.objects.get(username="admin").password

        assert hash_before == hash_after, "rehashed on a no-op run — fix check_password gate"

    def test_reconciles_is_staff_after_manual_clear(self, settings):
        """If is_staff is cleared in /admin/, the next deploy puts it back."""
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "secret"
        call_command("ensure_admin_user")

        user = User.objects.get(username="admin")
        user.is_staff = False
        user.is_superuser = False
        user.save()

        call_command("ensure_admin_user")

        user.refresh_from_db()
        assert user.is_staff is True
        assert user.is_superuser is True

    def test_no_op_when_password_unset(self, settings, capsys):
        """ADMIN_PASSWORD missing → command logs a warning, doesn't create the user."""
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = None

        call_command("ensure_admin_user")

        assert not User.objects.filter(username="admin").exists()
        captured = capsys.readouterr()
        assert "ADMIN_PASSWORD" in captured.out

    def test_changing_username_creates_new_user(self, settings):
        """Changing ADMIN_USERNAME creates a second admin instead of renaming."""
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "secret"
        call_command("ensure_admin_user")

        settings.ADMIN_USERNAME = "newadmin"
        call_command("ensure_admin_user")

        assert User.objects.filter(username="admin").exists()
        assert User.objects.filter(username="newadmin").exists()
        assert User.objects.filter(is_staff=True).count() == 2

    def test_idempotent_on_repeated_runs(self, settings):
        """Running 10 times in a row produces exactly one admin user."""
        settings.ADMIN_USERNAME = "admin"
        settings.ADMIN_PASSWORD = "secret"
        for _ in range(10):
            call_command("ensure_admin_user")

        assert User.objects.filter(username="admin").count() == 1


# =============================================================================
# ProcessingQueueAdmin — read-only overview of pending/processing Tests
# =============================================================================


class TestProcessingQueueAdmin:
    """The `ProcessingQueueTest` proxy model gives pending/processing rows their
    own read-only admin section, without touching the existing `core/test`
    changelist (which shows every Test regardless of status).
    """

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username="admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        client.login(username="admin", password="secret")
        return client

    def test_only_pending_and_processing_tests_are_listed(self, admin_client, test_factory):
        pending = test_factory(name="pending-test", status=Test.STATUS_PENDING)
        processing = test_factory(name="processing-test", status=Test.STATUS_PROCESSING)
        done = test_factory(name="done-test", status=Test.STATUS_DONE)
        failed = test_factory(name="failed-test", status=Test.STATUS_FAILED)

        response = admin_client.get("/admin/core/processingqueuetest/")

        assert response.status_code == 200
        assert pending.name.encode() in response.content
        assert processing.name.encode() in response.content
        assert done.name.encode() not in response.content
        assert failed.name.encode() not in response.content

    def test_no_add_link_on_changelist(self, admin_client, test_factory):
        """`has_add_permission` returning False hides the "Add" button."""
        test_factory(status=Test.STATUS_PENDING)

        response = admin_client.get("/admin/core/processingqueuetest/")

        assert response.status_code == 200
        assert b"Add processing queue" not in response.content

    def test_add_page_is_forbidden(self, admin_client):
        """Django's admin raises PermissionDenied (403) when `has_add_permission`
        is False and the /add/ URL is hit directly — unlike Project/Suite, which
        render a normal add form (see `test_add_page_loads` above).
        """
        response = admin_client.get("/admin/core/processingqueuetest/add/")
        assert response.status_code == 403

    def test_change_page_is_read_only(self, admin_client, test_factory):
        """`has_change_permission` returning False renders the detail page
        read-only (no Save button) — but the page itself still renders because
        `has_view_permission`'s default checks the view-or-change permission
        *strings*, and a superuser satisfies any permission check.
        """
        obj = test_factory(status=Test.STATUS_PENDING)

        response = admin_client.get(f"/admin/core/processingqueuetest/{obj.pk}/change/")

        assert response.status_code == 200
        assert b'<input type="submit"' not in response.content
        assert b"_save" not in response.content

    def test_delete_action_is_unavailable(self, admin_client, test_factory):
        """No delete link/button on the read-only detail page."""
        obj = test_factory(status=Test.STATUS_PENDING)

        response = admin_client.get(f"/admin/core/processingqueuetest/{obj.pk}/change/")

        assert response.status_code == 200
        assert b"Delete" not in response.content

    def test_waiting_since_column_renders(self, admin_client, test_factory):
        """Smoke-test for the custom `waiting_since` display method, mirroring
        `test_test_admin_changelist_shows_diff_pct_column` for `TestAdmin.diff_pct`.
        """
        test_factory(status=Test.STATUS_PENDING)
        response = admin_client.get("/admin/core/processingqueuetest/")
        assert response.status_code == 200

    def test_changelist_query_count_does_not_scale_with_row_count(
        self,
        admin_client,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        """`list_select_related` must prevent an N+1 on `run_label`, which walks
        run -> suite -> project for every row. Query count for a handful of
        rows across distinct runs/suites/projects should match the query count
        for a couple of rows — not grow with row count.
        """

        def _make_rows(count):
            for _i in range(count):
                project = project_factory()
                suite = suite_factory(project=project)
                run = run_factory(suite=suite)
                test_factory(run=run, status=Test.STATUS_PENDING)

        _make_rows(2)
        with CaptureQueriesContext(connection) as small:
            response = admin_client.get("/admin/core/processingqueuetest/")
        assert response.status_code == 200
        small_count = len(small.captured_queries)

        _make_rows(4)  # now 6 rows total, across 6 distinct projects/suites/runs
        with CaptureQueriesContext(connection) as large:
            response = admin_client.get("/admin/core/processingqueuetest/")
        assert response.status_code == 200
        large_count = len(large.captured_queries)

        assert large_count == small_count, (
            f"query count grew with row count ({small_count} -> {large_count}); "
            "list_select_related isn't preventing the N+1 on run_label"
        )


# =============================================================================
# ProcessingQueueAdmin.restart_processing — manual recovery action
# =============================================================================


class TestRestartProcessingAction:
    """`restart_processing` re-enqueues stuck pending/processing rows by hand.

    Exercised end-to-end through the admin changelist action endpoint (not by
    calling the method directly) so these tests also prove the action runs
    despite `has_change_permission` returning False on this ModelAdmin —
    Django gates actions by their own `allowed_permissions`, not
    `has_change_permission`, but that's worth confirming empirically rather
    than assuming it.
    """

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username="admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        client.login(username="admin", password="secret")
        return client

    def _run_action(self, admin_client, *tests):
        return admin_client.post(
            "/admin/core/processingqueuetest/",
            data={
                "action": "restart_processing",
                "_selected_action": [str(test.pk) for test in tests],
                "index": 0,
            },
            follow=True,
        )

    def test_restarts_test_when_staged_upload_present(self, admin_client, test_factory):
        test = test_factory(status=Test.STATUS_PROCESSING)
        staging_key = staging_key_for_test(test.id)

        with (
            patch("core.admin.get_s3_client") as mock_get_client,
            patch("core.admin.process_test.delay") as mock_delay,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            response = self._run_action(admin_client, test)

        assert response.status_code == 200
        mock_client.head_object.assert_called_once_with(Bucket=django_settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key)
        mock_delay.assert_called_once_with(test.id, staging_key)
        test.refresh_from_db()
        assert test.status == Test.STATUS_PENDING
        assert b"Restarted 1 test" in response.content

    def test_missing_staged_upload_is_reported_and_not_restarted(self, admin_client, test_factory):
        test = test_factory(status=Test.STATUS_PROCESSING)

        with (
            patch("core.admin.get_s3_client") as mock_get_client,
            patch("core.admin.process_test.delay") as mock_delay,
        ):
            mock_client = MagicMock()
            mock_client.head_object.side_effect = ClientError(
                {
                    "Error": {"Code": "404", "Message": "Not Found"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadObject",
            )
            mock_get_client.return_value = mock_client

            response = self._run_action(admin_client, test)

        assert response.status_code == 200
        mock_delay.assert_not_called()
        test.refresh_from_db()
        assert test.status == Test.STATUS_PROCESSING
        assert b"had no staged upload left in S3" in response.content

    def test_non_404_client_error_is_not_swallowed(self, admin_client, test_factory):
        """A 403/500/etc from S3 must surface loudly, not be reported as a
        harmless "missing staged upload" — that guidance would be actively
        wrong during a transient S3/network/permissions incident.
        """
        test = test_factory(status=Test.STATUS_PROCESSING)

        with (
            patch("core.admin.get_s3_client") as mock_get_client,
            patch("core.admin.process_test.delay") as mock_delay,
        ):
            mock_client = MagicMock()
            mock_client.head_object.side_effect = ClientError(
                {
                    "Error": {"Code": "403", "Message": "Forbidden"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "HeadObject",
            )
            mock_get_client.return_value = mock_client

            with pytest.raises(ClientError):
                self._run_action(admin_client, test)

        mock_delay.assert_not_called()
        test.refresh_from_db()
        assert test.status == Test.STATUS_PROCESSING

    def test_action_runs_despite_has_change_permission_false(self, admin_client, test_factory):
        """Regression guard for the read-only overrides on this ModelAdmin:
        `has_change_permission` returns False here, but that must not block
        this action from actually running end-to-end through the admin UI.
        """
        test = test_factory(status=Test.STATUS_PENDING)

        with (
            patch("core.admin.get_s3_client") as mock_get_client,
            patch("core.admin.process_test.delay") as mock_delay,
        ):
            mock_get_client.return_value = MagicMock()
            self._run_action(admin_client, test)

        mock_delay.assert_called_once()

    def test_no_queued_tests_shows_no_op_warning(self, admin_client, test_factory):
        """If the selected row already left pending/processing by the time the
        action runs (e.g. it finished between page load and clicking "Go"),
        `get_queryset` filters it out and the action's queryset ends up empty —
        both `restarted` and `missing` stay 0. The admin should still see
        feedback instead of a silent no-op reload.
        """
        test = test_factory(status=Test.STATUS_DONE)

        with (
            patch("core.admin.get_s3_client") as mock_get_client,
            patch("core.admin.process_test.delay") as mock_delay,
        ):
            mock_get_client.return_value = MagicMock()
            response = self._run_action(admin_client, test)

        assert response.status_code == 200
        mock_delay.assert_not_called()
        assert b"No queued tests to restart." in response.content


class TestDiscardFromQueueAction:
    """`discard_from_queue` permanently removes stuck rows and their staged
    S3 upload, behind a two-step confirmation like Django's built-in "Delete
    selected" action.
    """

    @pytest.fixture
    def admin_client(self, client):
        User.objects.create_user(
            username="admin",
            password="secret",
            is_staff=True,
            is_superuser=True,
        )
        client.login(username="admin", password="secret")
        return client

    def _run_action(self, admin_client, *tests, confirm=False):
        data = {
            "action": "discard_from_queue",
            "_selected_action": [str(test.pk) for test in tests],
            "index": 0,
        }
        if confirm:
            data["post"] = "yes"
        return admin_client.post("/admin/core/processingqueuetest/", data=data, follow=True)

    def test_unconfirmed_request_shows_confirmation_page_and_deletes_nothing(self, admin_client, test_factory):
        test = test_factory(status=Test.STATUS_PENDING)

        response = self._run_action(admin_client, test, confirm=False)

        assert response.status_code == 200
        assert str(test).encode() in response.content
        assert Test.objects.filter(pk=test.pk).exists()

    def test_unconfirmed_request_shows_cancel_link(self, admin_client, test_factory):
        """The confirmation page must offer a way back besides the browser's
        back button, matching Django's own delete-confirmation template.
        """
        test = test_factory(status=Test.STATUS_PENDING)

        response = self._run_action(admin_client, test, confirm=False)

        assert response.status_code == 200
        assert b"No, take me back" in response.content
        assert b"cancel-link" in response.content

    def test_confirmed_request_deletes_row_and_cleans_up_s3(self, admin_client, test_factory):
        test = test_factory(status=Test.STATUS_PROCESSING)
        staging_key = staging_key_for_test(test.id)

        with patch("core.admin.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            response = self._run_action(admin_client, test, confirm=True)

        assert response.status_code == 200
        assert not Test.objects.filter(pk=test.pk).exists()
        mock_client.delete_object.assert_called_once_with(
            Bucket=django_settings.AWS_STORAGE_BUCKET_NAME, Key=staging_key
        )
        assert b"Discarded 1 test(s)" in response.content

    def test_confirmed_request_on_multiple_rows_discards_all(self, admin_client, test_factory):
        pending = test_factory(status=Test.STATUS_PENDING)
        processing = test_factory(status=Test.STATUS_PROCESSING)

        with patch("core.admin.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            response = self._run_action(admin_client, pending, processing, confirm=True)

        assert response.status_code == 200
        assert not Test.objects.filter(pk__in=[pending.pk, processing.pk]).exists()
        assert mock_client.delete_object.call_count == 2

    def test_404_staged_upload_is_not_an_error(self, admin_client, test_factory):
        """A 404 (staged upload already gone) is fine and doesn't block the
        discard; the row is still deleted from the DB and success message shown.
        """
        test = test_factory(status=Test.STATUS_PROCESSING)

        with patch("core.admin.get_s3_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.delete_object.side_effect = ClientError(
                {
                    "Error": {"Code": "404", "Message": "Not Found"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "DeleteObject",
            )
            mock_get_client.return_value = mock_client

            response = self._run_action(admin_client, test, confirm=True)

        assert response.status_code == 200
        assert not Test.objects.filter(pk=test.pk).exists()
        assert b"Discarded 1 test(s)" in response.content

    def test_non_404_client_error_is_not_swallowed(self, admin_client, test_factory):
        """A 403/500/etc from S3 must surface loudly, not be treated as a
        harmless "already gone" — that would leave the row deleted in the DB
        while its staged upload silently leaks in S3.
        """
        test = test_factory(status=Test.STATUS_PROCESSING)

        with (
            patch("core.admin.get_s3_client") as mock_get_client,
        ):
            mock_client = MagicMock()
            mock_client.delete_object.side_effect = ClientError(
                {
                    "Error": {"Code": "403", "Message": "Forbidden"},
                    "ResponseMetadata": {"HTTPStatusCode": 403},
                },
                "DeleteObject",
            )
            mock_get_client.return_value = mock_client

            with pytest.raises(ClientError):
                self._run_action(admin_client, test, confirm=True)

        test.refresh_from_db()
        assert Test.objects.filter(pk=test.pk).exists()
