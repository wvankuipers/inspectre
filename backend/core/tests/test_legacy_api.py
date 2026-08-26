from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from rest_framework.test import APIClient

from core.models import Baseline, Project, Run, Suite, Test

pytestmark = pytest.mark.django_db


_FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "images" / "testcard.jpg"


@pytest.fixture
def api():
    """Anonymous client. The legacy endpoints are no-auth (decisions.md, public/API)."""
    return APIClient()


def _png_upload(name="homepage.jpg"):
    """Real, ImageMagick-readable upload. Each call returns a fresh stream."""
    return SimpleUploadedFile(
        name,
        _FIXTURE_IMAGE.read_bytes(),
        content_type="image/jpeg",
    )


# =============================================================================
# POST /runs
# =============================================================================


class TestRunsCreate:
    def test_creates_project_suite_and_run(self, api):
        response = api.post("/runs", {"project": "Acme Site", "suite": "Desktop"})

        assert response.status_code == 200
        body = response.json()
        assert body["suite_id"]
        assert body["sequential_id"] == 1
        assert body["url"] == "/projects/acme-site/suites/desktop/runs/1"

        assert Project.objects.get(name="Acme Site").slug == "acme-site"
        assert Suite.objects.get(name="Desktop").slug == "desktop"

    def test_reuses_existing_project_and_suite(self, api):
        api.post("/runs", {"project": "Acme Site", "suite": "Desktop"})
        api.post("/runs", {"project": "Acme Site", "suite": "Desktop"})

        assert Project.objects.count() == 1
        assert Suite.objects.count() == 1
        assert Run.objects.count() == 2

    def test_per_suite_sequential_id_increments(self, api):
        first = api.post("/runs", {"project": "P", "suite": "S"}).json()
        second = api.post("/runs", {"project": "P", "suite": "S"}).json()

        assert first["sequential_id"] == 1
        assert second["sequential_id"] == 2

    def test_different_suites_have_independent_sequential_ids(self, api):
        a = api.post("/runs", {"project": "P", "suite": "A"}).json()
        b = api.post("/runs", {"project": "P", "suite": "B"}).json()
        assert a["sequential_id"] == 1
        assert b["sequential_id"] == 1

    def test_response_includes_url_field(self, api):
        body = api.post("/runs", {"project": "P", "suite": "S"}).json()
        assert "url" in body
        assert body["url"].startswith("/projects/")

    def test_skip_csrf(self, api):
        """The Client API doesn't fetch a CSRF token; the endpoint must accept anonymous POSTs."""
        response = api.post("/runs", {"project": "P", "suite": "S"})
        assert response.status_code == 200

    @pytest.mark.parametrize(
        "payload,missing_field",
        [
            ({"suite": "Desktop"}, "project"),
            ({"project": "Acme"}, "suite"),
            ({"project": "", "suite": "Desktop"}, "project"),
            ({"project": "Acme", "suite": ""}, "suite"),
            ({}, "project"),
        ],
    )
    def test_missing_or_empty_project_or_suite_returns_400(self, api, payload, missing_field):
        response = api.post("/runs", payload)
        assert response.status_code == 400
        assert missing_field in response.json()


# =============================================================================
# POST /tests — slice 4a (stub: self-baseline only, no real diff)
# =============================================================================


def _post_test(api, run, **extras):
    """Helper: build the standard multipart payload for the legacy API."""
    payload = {
        "run_id": str(run.id),
        "name": "Homepage",
        "browser": "Chrome",
        "size": "1024",
        "screenshot": _png_upload(),
    }
    payload.update(extras)
    return api.post("/tests", payload, format="multipart")


def _post_test_async(api, run, **extras):
    """Post a test with mocked S3 staging and Celery task, returning (response, mock_task)."""
    with (
        patch("core.views.legacy.process_test") as mock_task,
        patch("core.views.legacy._stage_upload_to_s3") as mock_stage,
    ):
        mock_task.delay.return_value = None
        mock_stage.return_value = "screenshots/staging/99/upload.png"
        response = _post_test(api, run, **extras)
    return response, mock_task


class TestTestsCreate:
    def test_submission_returns_pending_status(self, api, run_factory):
        """POST /tests is now async — returns status=pending immediately."""
        run = run_factory()
        response, _ = _post_test_async(api, run)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["pass"] is False
        assert body["is_new_baseline"] is None

    def test_response_uses_pass_not_passed(self, api, run_factory):
        """The wire key is `"pass"`, not `"passed"`."""
        run = run_factory()
        body, _ = _post_test_async(api, run)
        body = body.json()

        assert "pass" in body
        assert "passed" not in body

    def test_submission_creates_test_row_and_enqueues_task(self, api, run_factory):
        """POST /tests creates a Test row and dispatches the Celery task."""
        run = run_factory()
        response, mock_task = _post_test_async(api, run)
        body = response.json()

        assert Test.objects.filter(pk=body["id"]).exists()
        mock_task.delay.assert_called_once_with(body["id"], "screenshots/staging/99/upload.png")

    def test_invalid_run_id_returns_404(self, api):
        response = api.post(
            "/tests",
            {
                "run_id": "99999",
                "name": "Homepage",
                "browser": "Chrome",
                "size": "1024",
                "screenshot": _png_upload(),
            },
            format="multipart",
        )
        assert response.status_code == 404

    def test_missing_screenshot_returns_400(self, api, run_factory):
        run = run_factory()
        response = api.post(
            "/tests",
            {
                "run_id": str(run.id),
                "name": "Homepage",
                "browser": "Chrome",
                "size": "1024",
            },
            format="multipart",
        )
        assert response.status_code == 400

    def test_missing_required_field_returns_400(self, api, run_factory):
        run = run_factory()
        response = api.post(
            "/tests",
            {
                "run_id": str(run.id),
                # name missing
                "browser": "Chrome",
                "size": "1024",
                "screenshot": _png_upload(),
            },
            format="multipart",
        )
        assert response.status_code == 400

    @pytest.mark.parametrize(
        "payload_template",
        [
            {"fuzz_level": "30%; touch {canary}"},
            {"highlight_colour": "ff0000'; touch {canary}"},
            {"crop_area": "200x150+0+0; touch {canary}"},
            {"fuzz_level": "banana%"},
            {"highlight_colour": "ff00"},  # not 6 chars
            {"crop_area": "200x"},  # malformed
        ],
    )
    def test_invalid_input_rejected_at_view(self, api, run_factory, tmp_path, payload_template):
        """Validator regexes run before any model row or shell command.

        decisions.md, "Bugs / risks fixed by the rebuild": every shell-injection
        vector and every malformed value lands here as a 400, never reaches the shell.
        """
        canary = tmp_path / "pwn_view"
        payload = {k: v.format(canary=canary) if isinstance(v, str) else v for k, v in payload_template.items()}

        run = run_factory()
        response = _post_test(api, run, **payload)

        assert response.status_code == 400, f"unexpected for {payload}: {response.content!r}"
        assert not canary.exists(), "shell-injection succeeded — validator regression"
        assert not Test.objects.filter(run=run).exists(), "malformed payload should not have created a Test row"

    @pytest.mark.parametrize("fuzz", ["101%", "100.1%", "9999%"])
    def test_fuzz_level_above_100_rejected(self, api, run_factory, fuzz):
        run = run_factory()
        response = _post_test(api, run, fuzz_level=fuzz)
        assert response.status_code == 400


# =============================================================================
# PATCH /tests/:id — "Set as baseline" from the legacy UI
# =============================================================================


class TestValidateTestParams:
    """Unit tests for validate_test_params — called directly with raw Python values."""

    _BASE = {"run_id": "1", "name": "Homepage", "browser": "Chrome", "size": "1024"}

    @pytest.mark.parametrize(
        "field,value",
        [
            ("fuzz_level", 30),
            ("fuzz_level", ["30%"]),
            ("highlight_colour", 0xFF0000),
            ("crop_area", [200, 150, 0, 0]),
        ],
    )
    def test_non_string_optional_fields_raise_validation_error(self, field, value):
        """Non-string values must produce a ValidationError, not a TypeError."""
        from rest_framework.exceptions import ValidationError

        from core.services.validation import validate_test_params

        with pytest.raises(ValidationError):
            validate_test_params({**self._BASE, field: value})

    @pytest.mark.parametrize("fuzz", ["101%", "100.1%", "9999%"])
    def test_fuzz_above_100_raises_validation_error(self, fuzz):
        from rest_framework.exceptions import ValidationError

        from core.services.validation import validate_test_params

        with pytest.raises(ValidationError):
            validate_test_params({**self._BASE, "fuzz_level": fuzz})


class TestTestsPatchSetBaseline:
    def test_legacy_patch_promotes_test(self, api, test_factory):
        """Failing test → PATCH with test[baseline]=true → passed=True, baseline updated."""
        from django.core.files.base import ContentFile

        # Create a test row with a screenshot file so upsert_baseline_from_test can copy it.
        test = test_factory(passed=False)
        test.screenshot.save("original.png", ContentFile(_FIXTURE_IMAGE.read_bytes()))

        response = api.patch(
            f"/tests/{test.id}",
            {"test[baseline]": "true"},
            format="multipart",
        )
        assert response.status_code == 200
        body = response.json()
        assert body["pass"] is True  # legacy API wire key

        # The baseline now points at this test.
        baseline = Baseline.objects.get(key=test.key)
        assert baseline.test_id == test.id

    def test_patch_without_baseline_param_is_noop(self, api, test_factory):
        test = test_factory(passed=False)

        response = api.patch(
            f"/tests/{test.id}",
            {},
            format="multipart",
        )
        assert response.status_code == 200

        assert Test.objects.get(pk=test.id).passed is False

    def test_patch_unknown_id_returns_404(self, api):
        response = api.patch(
            "/tests/999999",
            {"test[baseline]": "true"},
            format="multipart",
        )
        assert response.status_code == 404

    def test_failed_upsert_rolls_back_passed_flag(self, api, test_factory):
        """Regression: a failing upsert_baseline_row must not leave test.passed=True.

        Prior to wrapping _set_as_baseline in transaction.atomic(), test.save()
        committed passed=True immediately, so a subsequent upsert failure left
        the test falsely "passed" with no matching Baseline row.
        """
        test = test_factory(passed=False)

        with patch("core.services.baseline_upsert.upsert_baseline_row", side_effect=Exception("boom")):
            with pytest.raises(Exception, match="boom"):
                api.patch(
                    f"/tests/{test.id}",
                    {"test[baseline]": "true"},
                    format="multipart",
                )

        assert Test.objects.get(pk=test.id).passed is False
        assert not Baseline.objects.filter(key=test.key).exists()

    def test_failed_thumbnail_does_not_roll_back_promotion(self, api, test_factory):
        """A thumbnail-render failure is a side effect failure, not an atomic-invariant

        failure: the row upsert (test.passed + Baseline row) must survive even if
        attach_baseline_thumbnail_for_test blows up afterward.
        """
        from django.core.files.base import ContentFile

        test = test_factory(passed=False)
        test.screenshot.save("original.png", ContentFile(_FIXTURE_IMAGE.read_bytes()))

        with patch(
            "core.services.baseline_upsert.attach_baseline_thumbnail_for_test",
            side_effect=Exception("boom"),
        ):
            with pytest.raises(Exception, match="boom"):
                api.patch(
                    f"/tests/{test.id}",
                    {"test[baseline]": "true"},
                    format="multipart",
                )

        assert Test.objects.get(pk=test.id).passed is True
        assert Baseline.objects.filter(key=test.key).exists()


# =============================================================================
# GET /baselines/<key>.png and .json
# =============================================================================


class TestBaselineLookup:
    def test_png_returns_image_bytes(self, api, baseline_factory):
        """GET /baselines/<key>.png streams the screenshot bytes."""
        from django.core.files.base import ContentFile

        baseline = baseline_factory(key="test-key-png")
        baseline.screenshot.save("screenshot.png", ContentFile(_FIXTURE_IMAGE.read_bytes()))

        response = api.get(f"/baselines/{baseline.key}.png")
        assert response.status_code == 200
        assert response["Content-Type"].startswith("image/")
        assert len(b"".join(response.streaming_content)) > 0

    def test_json_returns_metadata(self, api, baseline_factory):
        from django.core.files.base import ContentFile

        baseline = baseline_factory(key="test-key-json")
        baseline.screenshot.save("screenshot.png", ContentFile(_FIXTURE_IMAGE.read_bytes()))

        response = api.get(f"/baselines/{baseline.key}.json")
        assert response.status_code == 200
        meta = response.json()
        assert meta["key"] == baseline.key
        assert meta["screenshot_url"]

    def test_unknown_key_returns_404(self, api):
        assert api.get("/baselines/no-such-key.png").status_code == 404
        assert api.get("/baselines/no-such-key.json").status_code == 404


# =============================================================================
# POST /tests — async path (Task 5)
# =============================================================================


class TestTestsCreateAsync:
    def test_returns_pending_status_immediately(self, api, run_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = False
        run = run_factory()

        with (
            patch("core.views.legacy.process_test") as mock_task,
            patch("core.views.legacy._stage_upload_to_s3") as mock_stage,
        ):
            mock_task.delay.return_value = None
            mock_stage.return_value = "screenshots/staging/99/upload.png"
            response = api.post(
                "/tests",
                {
                    "run_id": str(run.id),
                    "name": "Homepage",
                    "browser": "Chrome",
                    "size": "1024",
                    "screenshot": _png_upload(),
                },
                format="multipart",
            )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["pass"] is False
        assert body["diff"] == 0
        assert body["screenshot_uid"] is None

    def test_enqueues_celery_task_with_test_id_and_staging_key(self, api, run_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = False
        run = run_factory()

        with (
            patch("core.views.legacy.process_test") as mock_task,
            patch("core.views.legacy._stage_upload_to_s3") as mock_stage,
        ):
            mock_task.delay.return_value = None
            mock_stage.return_value = "screenshots/staging/99/upload.png"

            response = api.post(
                "/tests",
                {
                    "run_id": str(run.id),
                    "name": "Homepage",
                    "browser": "Chrome",
                    "size": "1024",
                    "screenshot": _png_upload(),
                },
                format="multipart",
            )

        body = response.json()
        mock_task.delay.assert_called_once_with(body["id"], "screenshots/staging/99/upload.png")

    def test_response_includes_is_new_baseline_as_none_when_pending(self, api, run_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = False
        run = run_factory()

        with (
            patch("core.views.legacy.process_test") as mock_task,
            patch("core.views.legacy._stage_upload_to_s3") as mock_stage,
        ):
            mock_task.delay.return_value = None
            mock_stage.return_value = "screenshots/staging/99/upload.png"
            response = api.post(
                "/tests",
                {
                    "run_id": str(run.id),
                    "name": "Homepage",
                    "browser": "Chrome",
                    "size": "1024",
                    "screenshot": _png_upload(),
                },
                format="multipart",
            )

        assert response.json()["is_new_baseline"] is None


# =============================================================================
# GET /tests/:id/status — async polling endpoint (Task 5)
# =============================================================================


class TestTestsDetail:
    def test_returns_test_by_id(self, api, test_factory):
        test = test_factory()
        response = api.get(f"/tests/{test.id}/status")
        assert response.status_code == 200
        body = response.json()
        assert body["id"] == test.id
        assert body["status"] == "pending"

    def test_returns_404_for_unknown_id(self, api):
        response = api.get("/tests/99999/status")
        assert response.status_code == 404

    def test_done_test_includes_is_new_baseline(self, api, test_factory):
        test = test_factory()
        test.status = "done"
        test.is_new_baseline = True
        test.save()

        body = api.get(f"/tests/{test.id}/status").json()
        assert body["status"] == "done"
        assert body["is_new_baseline"] is True


# =============================================================================
# Concurrency — sequential_id under select_for_update
# =============================================================================


@pytest.mark.skipif(
    "sqlite" in str(connection.settings_dict.get("ENGINE", "")),
    reason="select_for_update is a no-op on SQLite — would pass for the wrong reason",
)
class TestConcurrentRunCreation:
    @pytest.mark.slow
    def test_no_collision_under_threads(self, api, transactional_db):
        """Two POST /runs against the same suite → distinct sequential_ids,
        not collisions. Regression test for the race documented in data-model.md.
        """
        import threading

        # Pre-create the suite so both threads contend on next_run_seq, not on get_or_create.
        api.post("/runs", {"project": "P", "suite": "S"})

        results = []
        errors = []

        def worker():
            try:
                response = APIClient().post("/runs", {"project": "P", "suite": "S"})
                results.append(response.json()["sequential_id"])
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
        all_ids = sorted([1] + results)
        assert all_ids == [1, 2, 3, 4, 5, 6], f"sequential_id collision under concurrency: got {all_ids}"


# =============================================================================
# Full async pipeline integration — Task 8
# =============================================================================


@pytest.mark.slow
class TestAsyncTestProcessingIntegration:
    """Full end-to-end: POST /tests enqueues a task that runs via CELERY_TASK_ALWAYS_EAGER.

    S3 staging is mocked at the boto3 boundary so no real bucket is needed.
    The staging file is simulated by writing the uploaded bytes to a temp file
    and having the download mock copy them to the task's destination path.
    ScreenshotComparison runs for real (ImageMagick) against Django's
    FileSystemStorage (hermetic, provided by the autouse _filesystem_storage
    fixture in conftest.py).
    """

    def _run_post(self, api, run, staging_png_bytes):
        """POST /tests with S3 mocked; return (post_body, staging_key)."""
        captured = {}

        def fake_stage(test_id, screenshot_file):
            key = f"screenshots/staging/{test_id}/upload.png"
            captured["key"] = key
            captured["bytes"] = screenshot_file.read()
            return key

        def fake_download(key, destination):
            destination.write_bytes(captured["bytes"])

        with (
            patch("core.views.legacy._stage_upload_to_s3", side_effect=fake_stage),
            patch("core.tasks._download_staged_file", side_effect=fake_download),
            patch("core.tasks._delete_staged_file"),
        ):
            response = api.post(
                "/tests",
                {
                    "run_id": str(run.id),
                    "name": "Homepage",
                    "browser": "Chrome",
                    "size": "1024",
                    "screenshot": _png_upload(),
                },
                format="multipart",
            )

        return response.json()

    def test_post_then_poll_returns_done_with_all_fields(self, api, run_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True
        run = run_factory()

        post_body = self._run_post(api, run, b"")

        # The view serializes the in-memory test object (status=pending) even though
        # ALWAYS_EAGER ran the task synchronously and updated the DB.
        assert post_body["status"] == "pending"
        assert post_body["screenshot_uid"] is None

        # Poll endpoint does a fresh DB read — task has already finished.
        poll_body = api.get(f"/tests/{post_body['id']}/status").json()
        assert poll_body["status"] == "done"
        assert poll_body["pass"] in (True, False)
        assert poll_body["diff"] >= 0
        assert poll_body["is_new_baseline"] in (True, False)

    def test_first_submission_for_a_key_is_new_baseline(self, api, run_factory, settings):
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True
        run = run_factory()

        def fake_stage(test_id, screenshot_file):
            key = f"screenshots/staging/{test_id}/upload.png"
            fake_stage._bytes = screenshot_file.read()
            return key

        fake_stage._bytes = b""

        def fake_download(key, destination):
            destination.write_bytes(fake_stage._bytes)

        with (
            patch("core.views.legacy._stage_upload_to_s3", side_effect=fake_stage),
            patch("core.tasks._download_staged_file", side_effect=fake_download),
            patch("core.tasks._delete_staged_file"),
        ):
            post_body = api.post(
                "/tests",
                {
                    "run_id": str(run.id),
                    "name": "NewPage",
                    "browser": "Chrome",
                    "size": "1024",
                    "screenshot": _png_upload(),
                },
                format="multipart",
            ).json()

        poll_body = api.get(f"/tests/{post_body['id']}/status").json()
        assert poll_body["status"] == "done"
        assert poll_body["is_new_baseline"] is True
        assert poll_body["pass"] is False
