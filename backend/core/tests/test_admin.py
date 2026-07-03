import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command

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
