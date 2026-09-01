from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
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

    def test_query_count_does_not_scale_with_suite_count(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        baseline_factory,
        django_assert_num_queries,
    ):
        """Regression test for the ProjectSerializer/RunSummarySerializer N+1: prior to the
        fix, RunSummarySerializer.get_unbaselined issued one extra Baseline query per suite
        because ProjectSerializer.get_suites never passed `baselined_keys` via context. With
        the fix, that query is issued once per project regardless of suite count.
        """
        project = project_factory(name="Acme")
        num_suites = 3
        for i in range(num_suites):
            suite = suite_factory(project=project, name=f"Suite {i}")
            run_factory(suite=suite)
            baseline_factory(suite=suite, key=f"acme-suite-{i}-key")

        # 3 fixed queries: select projects, prefetch suites, prefetch runs.
        # + 1 query for baselined_keys (once per project, not once per suite).
        # + 2 build_run_counts aggregate queries (passing/failing GROUP BY, unbaselined
        #   GROUP BY) covering every suite's latest run in one shot each — constant per
        #   project, never scaling with num_suites.
        expected_queries = 3 + 1 + 2
        with django_assert_num_queries(expected_queries):
            response = api.get("/api/projects/")

        assert response.status_code == 200
        body = response.json()
        assert len(body[0]["suites"]) == num_suites
        for suite_payload in body[0]["suites"]:
            assert suite_payload["latest_run"]["unbaselined"] == 0

    def test_query_count_does_not_scale_with_suite_count_when_no_baselines_exist(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
        django_assert_num_queries,
    ):
        """Regression test: when a project's suites collectively have zero baselines,
        `self.context.get("baselined_keys")` returns an empty set. Using `or` to check
        for that (instead of `is None`) treats the empty set as falsy and falls through
        to the per-suite fallback query, silently reintroducing the N+1 in exactly this
        state. Asserts the fixed query count holds here too.
        """
        project = project_factory(name="Acme")
        num_suites = 3
        for i in range(num_suites):
            suite = suite_factory(project=project, name=f"Suite {i}")
            run = run_factory(suite=suite)
            test_factory(run=run, key=f"acme-suite-{i}-key", passed=True)
        # No baselines created anywhere for this project.

        expected_queries = 3 + 1 + 2
        with django_assert_num_queries(expected_queries):
            response = api.get("/api/projects/")

        assert response.status_code == 200
        body = response.json()
        assert len(body[0]["suites"]) == num_suites
        for suite_payload in body[0]["suites"]:
            assert suite_payload["latest_run"]["unbaselined"] == 1

    def test_query_count_does_not_scale_with_total_suites_across_projects(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        baseline_factory,
        django_assert_num_queries,
    ):
        """The two tests above only prove constant-per-suite cost within a single
        project. This test proves the fix holds across multiple projects too: total
        query count scales with project count P, never with total suite count S.
        """
        num_projects = 2
        num_suites_per_project = 3
        for p in range(num_projects):
            project = project_factory(name=f"Project {p}")
            for i in range(num_suites_per_project):
                suite = suite_factory(project=project, name=f"Suite {p}-{i}")
                run_factory(suite=suite)
                baseline_factory(suite=suite, key=f"project-{p}-suite-{i}-key")

        # 3 fixed queries total (select projects, prefetch suites, prefetch runs)
        # + P * (1 baselined_keys query + 2 build_run_counts queries) — one set per
        # project, independent of total suite count across all projects.
        expected_queries = 3 + num_projects * (1 + 2)
        with django_assert_num_queries(expected_queries):
            response = api.get("/api/projects/")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == num_projects
        for project_payload in body:
            assert len(project_payload["suites"]) == num_suites_per_project
            for suite_payload in project_payload["suites"]:
                assert suite_payload["latest_run"]["unbaselined"] == 0


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

    def test_has_baseline_resolves_per_test_through_run_detail(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
        baseline_factory,
    ):
        """The run-detail endpoint is what the SPA's "new baseline" chip actually
        reads — has_baseline must resolve correctly here too, not just via the
        bulk endpoint's tests.
        """
        project = project_factory(name="Acme")
        suite = suite_factory(project=project, name="Desktop")
        run = run_factory(suite=suite)

        baselined = test_factory(run=run, name="Homepage")
        baseline_factory(suite=suite, key=baselined.key, test=baselined)
        test_factory(run=run, name="About")

        response = api.get(f"/api/projects/acme/suites/desktop/runs/{run.sequential_id}/")

        assert response.status_code == 200
        body = response.json()
        by_name = {t["name"]: t for t in body["tests"]}
        assert by_name["Homepage"]["has_baseline"] is True
        assert by_name["About"]["has_baseline"] is False

    def test_has_baseline_query_count_does_not_scale_with_test_count_when_no_baselines_exist(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        """Regression test for the same falsy-empty-set bug as
        RunSummarySerializer.get_unbaselined (see test_query_count_does_not_scale_with_
        suite_count_when_no_baselines_exist above), but in
        TestRowSerializer.get_has_baseline: `self.context.get("baselined_keys") or set(...)`
        treated a legitimate empty set (a suite with zero baselines) as absent, falling
        through to a per-row Baseline query — an N+1 on this run-detail endpoint. Prove the
        query count is the same regardless of how many test rows the run has.
        """
        project = project_factory(name="Acme")
        suite = suite_factory(project=project, name="Desktop")

        def _run_detail_query_count(num_tests):
            run = run_factory(suite=suite)
            for i in range(num_tests):
                test_factory(run=run, name=f"Test {i}", passed=True)
            with CaptureQueriesContext(connection) as ctx:
                response = api.get(f"/api/projects/acme/suites/desktop/runs/{run.sequential_id}/")
            assert response.status_code == 200
            assert len(response.json()["tests"]) == num_tests
            return len(ctx.captured_queries)

        assert _run_detail_query_count(1) == _run_detail_query_count(5)


# =============================================================================
# GET /api/projects/<slug>/suites/<slug>/tests/<key>/  — test history
# =============================================================================


class TestTestHistory:
    def test_returns_history_newest_run_first(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        project = project_factory(name="Acme")
        suite = suite_factory(project=project, name="Desktop")
        run1 = run_factory(suite=suite)
        run2 = run_factory(suite=suite)

        older = test_factory(
            run=run1,
            name="Homepage",
            browser="Chrome",
            size="1024",
            original_passed=True,
            is_new_baseline=True,
            status="done",
        )
        newer = test_factory(
            run=run2,
            name="Homepage",
            browser="Chrome",
            size="1024",
            original_passed=False,
            is_new_baseline=False,
            status="done",
        )
        assert older.key == newer.key

        response = api.get(f"/api/projects/acme/suites/desktop/tests/{older.key}/")

        assert response.status_code == 200
        body = response.json()
        assert body["key"] == older.key
        assert body["name"] == "Homepage"
        assert body["browser"] == "Chrome"
        assert body["size"] == "1024"
        assert body["project_name"] == "Acme"
        assert body["suite_slug"] == "desktop"

        run_ids = [entry["id"] for entry in body["runs"]]
        assert run_ids == [newer.id, older.id]  # newest run first

        newest_entry, oldest_entry = body["runs"]
        assert newest_entry["original_passed"] is False
        assert newest_entry["is_new_baseline"] is False
        assert newest_entry["status"] == "done"
        assert newest_entry["run_sequential_id"] == run2.sequential_id

        assert oldest_entry["original_passed"] is True
        assert oldest_entry["is_new_baseline"] is True
        assert oldest_entry["run_sequential_id"] == run1.sequential_id

    def test_unknown_key_returns_404(self, api, project_factory, suite_factory):
        project = project_factory(name="Acme")
        suite_factory(project=project, name="Desktop")

        assert api.get("/api/projects/acme/suites/desktop/tests/no-such-key/").status_code == 404

    def test_scoped_to_suite_and_project(
        self,
        api,
        project_factory,
        suite_factory,
        run_factory,
        test_factory,
    ):
        """A test with the same name/browser/size in a different suite must not
        leak into another suite's history — even though the raw key text would
        collide if the suites/projects were named identically.
        """
        project_a = project_factory(name="Acme")
        suite_a = suite_factory(project=project_a, name="Desktop")
        run_a = run_factory(suite=suite_a)
        test_a = test_factory(run=run_a, name="Homepage", browser="Chrome", size="1024")

        project_b = project_factory(name="Other Co")
        suite_b = suite_factory(project=project_b, name="Mobile")
        run_b = run_factory(suite=suite_b)
        test_factory(run=run_b, name="Homepage", browser="Chrome", size="1024")

        response = api.get(f"/api/projects/acme/suites/desktop/tests/{test_a.key}/")

        assert response.status_code == 200
        body = response.json()
        assert [entry["id"] for entry in body["runs"]] == [test_a.id]

        # Cross-suite: test_a's key doesn't exist under suite_b.
        assert api.get(f"/api/projects/other-co/suites/mobile/tests/{test_a.key}/").status_code == 404

    def test_promoted_test_still_reports_original_passed_false(self, api, test_factory):
        """Regression: promoting a failed test to baseline flips `passed` to True,
        but original_passed — the immutable diff-pipeline result — must stay False.
        """
        test = test_factory(passed=False, original_passed=False)
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

        suite = test.run.suite
        history = api.get(f"/api/projects/{suite.project.slug}/suites/{suite.slug}/tests/{test.key}/").json()

        entry = history["runs"][0]
        assert entry["original_passed"] is False

        test.refresh_from_db()
        assert test.passed is True


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
# POST /api/tests/bulk/  — fetch a specific set of tests by id
# =============================================================================


class TestTestsBulk:
    def test_returns_matching_tests(self, api, test_factory):
        t1 = test_factory(name="Homepage")
        t2 = test_factory(name="About")
        test_factory(name="Contact")  # not requested, must be excluded

        response = api.post(
            "/api/tests/bulk/",
            {"ids": [t1.id, t2.id]},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert {t["name"] for t in body} == {"Homepage", "About"}
        assert {t["id"] for t in body} == {t1.id, t2.id}

    def test_test_row_uses_passed_not_pass(self, api, test_factory):
        t1 = test_factory(name="Homepage")

        body = api.post("/api/tests/bulk/", {"ids": [t1.id]}, format="json").json()

        assert "passed" in body[0]
        assert isinstance(body[0]["passed"], bool)
        assert "pass" not in body[0]

    def test_unknown_ids_are_silently_omitted(self, api, test_factory):
        t1 = test_factory(name="Homepage")

        response = api.post(
            "/api/tests/bulk/",
            {"ids": [t1.id, 999999]},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert {t["id"] for t in body} == {t1.id}

    def test_empty_ids_returns_empty_array(self, api):
        response = api.post("/api/tests/bulk/", {"ids": []}, format="json")

        assert response.status_code == 200
        assert response.json() == []

    def test_ids_spanning_two_suites_resolve_baseline_source_independently(
        self,
        api,
        test_factory,
        baseline_factory,
    ):
        t1 = test_factory(name="Homepage")
        t2 = test_factory(name="Homepage")  # different run/suite (default factory)

        baseline_factory(suite=t1.run.suite, key=t1.key, test=t1)
        # t2's suite has no baseline pointing at t2.

        body = api.post(
            "/api/tests/bulk/",
            {"ids": [t1.id, t2.id]},
            format="json",
        ).json()

        by_id = {t["id"]: t for t in body}
        assert by_id[t1.id]["is_baseline_source"] is True
        assert by_id[t2.id]["is_baseline_source"] is False

    def test_superseded_test_still_reports_has_baseline_true(
        self,
        api,
        test_factory,
        baseline_factory,
    ):
        """A test that was once the baseline source but got superseded by a later
        test sharing its key must keep has_baseline=True even though
        is_baseline_source flips to False — this is the supersession bug fixed
        by the suite-scoped has_baseline signal.
        """
        test_a = test_factory(name="Homepage")
        baseline_factory(suite=test_a.run.suite, key=test_a.key, test=test_a)

        # test_b shares test_a's suite/name/browser/size, so it computes the same key.
        test_b = test_factory(
            run=test_a.run,
            name=test_a.name,
            browser=test_a.browser,
            size=test_a.size,
        )
        assert test_b.key == test_a.key

        # Simulate a later approval superseding test_a as the baseline source.
        baseline = test_a.run.suite.baselines.get(key=test_a.key)
        baseline.test = test_b
        baseline.save()

        body = api.post("/api/tests/bulk/", {"ids": [test_a.id]}, format="json").json()

        assert body[0]["is_baseline_source"] is False
        assert body[0]["has_baseline"] is True

    def test_test_with_no_baseline_reports_has_baseline_false(self, api, test_factory):
        t1 = test_factory(name="Homepage")

        body = api.post("/api/tests/bulk/", {"ids": [t1.id]}, format="json").json()

        assert body[0]["has_baseline"] is False

    def test_non_integer_ids_are_silently_filtered(self, api, test_factory):
        t1 = test_factory(name="Homepage")

        response = api.post(
            "/api/tests/bulk/",
            {"ids": [t1.id, "abc", None, 999999]},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == t1.id

    def test_all_invalid_ids_returns_empty_array(self, api):
        response = api.post(
            "/api/tests/bulk/",
            {"ids": ["abc", None, "test"]},
            format="json",
        )

        assert response.status_code == 200
        assert response.json() == []

    def test_booleans_are_filtered_out_of_ids(self, api, test_factory):
        t1 = test_factory(name="Homepage")

        response = api.post(
            "/api/tests/bulk/",
            {"ids": [t1.id, True, False]},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == t1.id

    def test_non_dict_body_returns_empty_array_instead_of_500(self, api):
        response = api.post("/api/tests/bulk/", [1, 2], format="json")

        assert response.status_code == 200
        assert response.json() == []

    def test_non_list_ids_returns_empty_array(self, api):
        response = api.post("/api/tests/bulk/", {"ids": 5}, format="json")

        assert response.status_code == 200
        assert response.json() == []

    def test_duplicate_ids_are_deduplicated(self, api, test_factory):
        t1 = test_factory(name="Homepage")

        response = api.post(
            "/api/tests/bulk/",
            {"ids": [t1.id, t1.id, t1.id]},
            format="json",
        )

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["id"] == t1.id

    def test_id_count_is_capped(self, api, test_factory):
        from core.views import api as api_module

        monkeypatch_cap = 2
        original_cap = api_module.MAX_BULK_TEST_IDS
        api_module.MAX_BULK_TEST_IDS = monkeypatch_cap
        try:
            tests = [test_factory(name=f"Test {i}") for i in range(3)]
            response = api.post(
                "/api/tests/bulk/",
                {"ids": [t.id for t in tests]},
                format="json",
            )

            assert response.status_code == 200
            body = response.json()
            assert len(body) == monkeypatch_cap
            assert {t["id"] for t in body} == {tests[0].id, tests[1].id}
        finally:
            api_module.MAX_BULK_TEST_IDS = original_cap


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
