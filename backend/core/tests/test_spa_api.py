from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


_FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "images" / "testcard.jpg"


@pytest.fixture
def api():
    return APIClient()


def _png_upload(name="homepage.jpg"):
    return SimpleUploadedFile(
        name,
        _FIXTURE_IMAGE.read_bytes(),
        content_type="image/jpeg",
    )


def _post_run(api, project="Acme", suite="Desktop"):
    """Helper: hit the legacy POST /runs to seed a Run for the SPA endpoints."""
    return api.post("/runs", {"project": project, "suite": suite}).json()


def _post_test(api, run_id, **extras):
    """Helper: hit the legacy POST /tests so Test rows exist for read endpoints.
    Mocks out S3 staging and Celery to avoid real I/O in unit tests.
    """
    payload = {
        "run_id": str(run_id),
        "name": "Homepage",
        "browser": "Chrome",
        "size": "1024",
        "screenshot": _png_upload(),
    }
    payload.update(extras)
    with (
        patch("core.views.legacy.process_test") as mock_task,
        patch("core.views.legacy._stage_upload_to_s3") as mock_stage,
    ):
        mock_task.delay.return_value = None
        mock_stage.return_value = "screenshots/staging/0/upload.png"
        return api.post("/tests", payload, format="multipart").json()


# =============================================================================
# GET /api/projects/  — projects list
# =============================================================================


class TestProjectsList:
    def test_returns_alphabetically_sorted_projects(self, api, project_factory):
        project_factory(name="Zeta")
        project_factory(name="Alpha")
        project_factory(name="Mu")

        body = api.get("/api/projects/").json()
        assert [p["name"] for p in body] == ["Alpha", "Mu", "Zeta"]

    def test_each_project_includes_its_suites(
        self,
        api,
        project_factory,
        suite_factory,
    ):
        project = project_factory(name="Acme")
        suite_factory(project=project, name="Desktop")
        suite_factory(project=project, name="Mobile")

        body = api.get("/api/projects/").json()
        names = {s["name"] for s in body[0]["suites"]}
        assert names == {"Desktop", "Mobile"}

    def test_suite_payload_includes_latest_run_summary(self, api):
        # POST twice so sequential_id == 2 is the latest.
        _post_run(api, project="Acme", suite="Desktop")
        _post_run(api, project="Acme", suite="Desktop")

        body = api.get("/api/projects/").json()
        suite_payload = body[0]["suites"][0]
        assert suite_payload["latest_run"]["sequential_id"] == 2

    def test_suite_with_no_runs_has_null_latest_run(
        self,
        api,
        project_factory,
        suite_factory,
    ):
        project = project_factory(name="Acme")
        suite_factory(project=project, name="Empty")

        body = api.get("/api/projects/").json()
        assert body[0]["suites"][0]["latest_run"] is None

    def test_empty_state_returns_empty_array(self, api):
        assert api.get("/api/projects/").json() == []


# =============================================================================
# GET /api/projects/<slug>/suites/<slug>/  — suite detail
# =============================================================================


class TestSuiteDetail:
    def test_returns_latest_5_runs_and_baselines(self, api, settings):
        settings.RUN_RETENTION_PER_SUITE = 5

        for _ in range(8):
            _post_run(api, project="Acme", suite="Desktop")
        # purge_old_runs keeps 5; the SPA never sees more.

        response = api.get("/api/projects/acme/suites/desktop/")
        assert response.status_code == 200
        body = response.json()
        assert len(body["latest_runs"]) == 5
        assert body["baselines"] == []

    def test_uses_current_slug_after_rename(
        self,
        api,
        project_factory,
        suite_factory,
    ):
        """decisions.md #4: rename re-slugs the project; URL the SPA uses follows."""
        project = project_factory(name="Acme")
        suite_factory(project=project, name="Desktop")

        assert api.get("/api/projects/acme/suites/desktop/").status_code == 200

        project.name = "Acme Inc"
        project.save()

        assert api.get("/api/projects/acme/suites/desktop/").status_code == 404
        assert api.get("/api/projects/acme-inc/suites/desktop/").status_code == 200

    def test_unknown_project_or_suite_returns_404(
        self,
        api,
        project_factory,
        suite_factory,
    ):
        project = project_factory(name="Acme")
        suite_factory(project=project, name="Desktop")

        assert api.get("/api/projects/no-such-project/suites/desktop/").status_code == 404
        assert api.get("/api/projects/acme/suites/no-such-suite/").status_code == 404


# =============================================================================
# GET /api/projects/<slug>/suites/<slug>/runs/<seq>/  — run detail
# =============================================================================


class TestRunDetail:
    def test_returns_run_with_inline_tests(self, api):
        run = _post_run(api, project="Acme", suite="Desktop")
        _post_test(api, run["id"], name="Homepage")
        _post_test(api, run["id"], name="About")

        response = api.get(f"/api/projects/acme/suites/desktop/runs/{run['sequential_id']}/")
        assert response.status_code == 200
        body = response.json()
        assert body["sequential_id"] == run["sequential_id"]
        assert {t["name"] for t in body["tests"]} == {"Homepage", "About"}

    def test_test_row_uses_passed_not_pass(self, api):
        """The SPA's wire format uses `passed`; the legacy API uses `pass`."""
        run = _post_run(api, project="Acme", suite="Desktop")
        _post_test(api, run["id"])

        body = api.get(f"/api/projects/acme/suites/desktop/runs/{run['sequential_id']}/").json()
        test = body["tests"][0]
        assert "passed" in test
        assert isinstance(test["passed"], bool)
        assert "pass" not in test, "leaked the legacy wire format into the SPA payload"

    def test_unknown_seq_id_returns_404(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
    ):
        project = project_factory(name="Acme")
        suite = suite_factory(project=project, name="Desktop")
        run_factory(suite=suite)  # sequential_id == 1

        assert api.get("/api/projects/acme/suites/desktop/runs/999/").status_code == 404


# =============================================================================
# POST /api/tests/<id>/set-baseline/  — SPA-preferred shape
# =============================================================================


class TestSetBaselineSpa:
    def test_promotes_test_to_baseline(self, api, test_factory):
        test = test_factory(passed=False)
        # Service path requires a screenshot. Attach one inline.
        test.screenshot.save(
            "s.png",
            SimpleUploadedFile(
                "s.png",
                _FIXTURE_IMAGE.read_bytes(),
                content_type="image/jpeg",
            ),
        )
        test.save()

        response = api.post(f"/api/tests/{test.id}/set-baseline/", {}, format="json")

        assert response.status_code == 204
        assert response.content == b""
        test.refresh_from_db()
        assert test.passed is True

    def test_body_content_is_ignored(self, api, test_factory):
        """A malicious client sending `{"pass": false}` cannot un-promote a test."""
        test = test_factory(passed=False)
        test.screenshot.save(
            "s.png",
            SimpleUploadedFile(
                "s.png",
                _FIXTURE_IMAGE.read_bytes(),
                content_type="image/jpeg",
            ),
        )
        test.save()

        api.post(
            f"/api/tests/{test.id}/set-baseline/",
            data={"pass": False, "passed": False, "baseline": False},
            format="json",
        )
        test.refresh_from_db()
        assert test.passed is True  # promoted regardless

    def test_unknown_id_returns_404(self, api):
        assert (
            api.post(
                "/api/tests/999999/set-baseline/",
                {},
                format="json",
            ).status_code
            == 404
        )

    def test_idempotent_on_already_passed_test(self, api, test_factory):
        test = test_factory(passed=True)
        test.screenshot.save(
            "s.png",
            SimpleUploadedFile(
                "s.png",
                _FIXTURE_IMAGE.read_bytes(),
                content_type="image/jpeg",
            ),
        )
        test.save()

        first = api.post(f"/api/tests/{test.id}/set-baseline/", {}, format="json")
        second = api.post(f"/api/tests/{test.id}/set-baseline/", {}, format="json")

        assert first.status_code == 204
        assert second.status_code == 204
        test.refresh_from_db()
        assert test.passed is True


# =============================================================================
# GET /api/baselines/<key>/  — JSON metadata
# =============================================================================


class TestBaselineDetailSpa:
    def test_returns_baseline_metadata(self, api, baseline_factory):
        from django.core.files.base import ContentFile

        baseline = baseline_factory(key="spa-test-key")
        baseline.screenshot.save("screenshot.png", ContentFile(_FIXTURE_IMAGE.read_bytes()))

        response = api.get(f"/api/baselines/{baseline.key}/")
        assert response.status_code == 200
        meta = response.json()
        assert meta["key"] == baseline.key
        assert meta["screenshot_url"]

    def test_unknown_key_returns_404(self, api):
        assert api.get("/api/baselines/no-such-key/").status_code == 404
