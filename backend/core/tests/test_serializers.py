import pytest

from core.serializers import (
    BaselineSerializer,
    LegacyBaselineSerializer,
    LegacyRunSerializer,
    LegacyTestSerializer,
    ProjectSerializer,
    RunDetailSerializer,
    RunSummarySerializer,
    SuiteDetailSerializer,
    TestHistoryEntrySerializer,
    TestRowSerializer,
    build_run_counts,
    serialize_test_history,
)

pytestmark = pytest.mark.django_db


# ---- Frozen field sets ----------------------------------------------------
# These literals pin the wire format. Updating one is a wire-format change;
# review carefully.

LEGACY_RUN_FIELDS = frozenset(
    {
        "id",
        "suite_id",
        "sequential_id",
        "created_at",
        "updated_at",
        "url",
    }
)

LEGACY_TEST_FIELDS = frozenset(
    {
        "id",
        "name",
        "browser",
        "size",
        "run_id",
        "diff",
        "screenshot_uid",
        "screenshot_baseline_uid",
        "screenshot_diff_uid",
        "key",
        "pass",
        "source_url",
        "fuzz_level",
        "highlight_colour",
        "crop_area",
        "created_at",
        "updated_at",
        "url",
        "status",
    }
)

LEGACY_BASELINE_FIELDS = frozenset(
    {
        "id",
        "name",
        "browser",
        "size",
        "suite_id",
        "key",
        "test_id",
        "screenshot_url",
        "created_at",
        "updated_at",
    }
)


# ---- The single most important assertion in this file --------------------


def test_legacy_test_serializer_uses_pass_not_passed(test_factory):
    """The wire format is `"pass"`, never `"passed"` or `"pass_field"`.

    This is the regression that breaks every CI pipeline using the legacy API.
    """
    test = test_factory(passed=True)
    body = LegacyTestSerializer(test).data

    assert "pass" in body
    assert body["pass"] is True
    assert "passed" not in body
    assert "pass_field" not in body


def test_legacy_test_serializer_pass_reflects_model_state(test_factory):
    """Both branches of `passed` round-trip correctly to the wire `"pass"` key."""
    passing = test_factory(passed=True)
    failing = test_factory(passed=False)

    assert LegacyTestSerializer(passing).data["pass"] is True
    assert LegacyTestSerializer(failing).data["pass"] is False


# ---- Frozen field-set checks ---------------------------------------------


@pytest.mark.parametrize(
    "serializer_cls,factory_name,expected_fields",
    [
        (LegacyRunSerializer, "run_factory", LEGACY_RUN_FIELDS),
        (LegacyTestSerializer, "test_factory", LEGACY_TEST_FIELDS),
    ],
)
def test_legacy_serializer_field_set_is_frozen(
    serializer_cls,
    factory_name,
    expected_fields,
    request,
):
    """Adding a field to the model must NOT silently appear in the legacy response.

    If this test fails because a new field appeared, ask:
    - Was the field added because the Client API now expects it? Update LEGACY_*_FIELDS.
    - Was it accidental? Remove the field from the legacy serializer's `fields`.
    """
    factory = request.getfixturevalue(factory_name)
    body = serializer_cls(factory()).data
    assert frozenset(body.keys()) == expected_fields


def test_legacy_baseline_serializer_field_set_is_frozen(baseline_factory):
    body = LegacyBaselineSerializer(baseline_factory()).data
    assert frozenset(body.keys()) == LEGACY_BASELINE_FIELDS


# ---- URL shape — survives renames ----------------------------------------


def test_legacy_run_url_uses_current_slug_after_rename(run_factory):
    """LegacyRunSerializer.url reflects the current slug, not the slug at run-creation.

    decisions.md #4: rename re-slugs the project, and the URL should follow.
    """
    run = run_factory()
    run.suite.project.name = "Renamed Project"
    run.suite.project.save()

    body = LegacyRunSerializer(run).data
    assert body["url"].startswith("/projects/renamed-project/suites/")


def test_legacy_test_url_includes_anchor(test_factory):
    test = test_factory()
    body = LegacyTestSerializer(test).data
    assert body["url"].endswith(f"#test_{test.id}")


def test_legacy_test_serializer_includes_status(test_factory):
    test = test_factory()
    body = LegacyTestSerializer(test).data
    assert "status" in body
    assert body["status"] == "pending"


def test_spa_test_row_serializer_includes_status(test_factory):
    body = TestRowSerializer(test_factory()).data
    assert "status" in body
    assert body["status"] == "pending"


# ---- File URLs — None when storage is empty -------------------------------


def test_legacy_test_serializer_uid_fields_are_none_when_no_file(test_factory):
    """Mid-comparison Tests have no attached files yet → uid fields are null, not '/'."""
    body = LegacyTestSerializer(test_factory()).data

    assert body["screenshot_uid"] is None
    assert body["screenshot_baseline_uid"] is None
    assert body["screenshot_diff_uid"] is None


def test_legacy_test_serializer_uid_fields_are_presigned(test_factory, monkeypatch):
    """Legacy uid fields delegate to the same presigning helper as the SPA fields."""
    from django.core.files.base import ContentFile

    monkeypatch.setattr(
        "core.serializers.generate_presigned_url",
        lambda key, expires_in=86400: f"https://signed.example/{key}?exp={expires_in}",
    )

    test = test_factory()
    test.screenshot.save("original.png", ContentFile(b"fake-image-bytes"))

    body = LegacyTestSerializer(test).data
    assert body["screenshot_uid"] == f"https://signed.example/{test.screenshot.name}?exp=86400"


def test_legacy_baseline_serializer_screenshot_url_is_presigned(baseline_factory, monkeypatch):
    from django.core.files.base import ContentFile

    monkeypatch.setattr(
        "core.serializers.generate_presigned_url",
        lambda key, expires_in=86400: f"https://signed.example/{key}?exp={expires_in}",
    )

    baseline = baseline_factory()
    baseline.screenshot.save("screenshot.png", ContentFile(b"fake-image-bytes"))

    body = LegacyBaselineSerializer(baseline).data
    assert body["screenshot_url"] == f"https://signed.example/{baseline.screenshot.name}?exp=86400"


@pytest.mark.parametrize(
    "url_field",
    [
        "screenshot_url",
        "baseline_url",
        "diff_url",
        "screenshot_thumb_url",
        "baseline_thumb_url",
        "diff_thumb_url",
    ],
)
def test_spa_test_row_url_fields_are_none_when_no_file(test_factory, url_field):
    """Same invariant on the SPA side: missing FileFields render as null, not as a broken URL."""
    body = TestRowSerializer(test_factory()).data
    assert body[url_field] is None


def test_spa_test_row_screenshot_url_is_presigned(test_factory, monkeypatch):
    """_file_url delegates to generate_presigned_url, not the raw storage .url."""
    from django.core.files.base import ContentFile

    monkeypatch.setattr(
        "core.serializers.generate_presigned_url",
        lambda key, expires_in=86400: f"https://signed.example/{key}?exp={expires_in}",
    )

    test = test_factory()
    test.screenshot.save("original.png", ContentFile(b"fake-image-bytes"))

    body = TestRowSerializer(test).data
    assert body["screenshot_url"] == f"https://signed.example/{test.screenshot.name}?exp=86400"


# ---- SPA-side latest_runs limit ------------------------------------------


def test_suite_detail_serializer_returns_at_most_5_runs(suite_factory, run_factory, settings):
    """purge_old_runs keeps RUN_RETENTION_PER_SUITE; verify the serializer surfaces them all."""
    settings.RUN_RETENTION_PER_SUITE = 5
    suite = suite_factory()
    for _ in range(8):
        run_factory(suite=suite)

    body = SuiteDetailSerializer(suite).data
    assert len(body["latest_runs"]) == 5


def test_suite_detail_serializer_includes_project_name(suite_factory, project_factory):
    project = project_factory(name="Acme Corp")
    suite = suite_factory(project=project)
    body = SuiteDetailSerializer(suite).data
    assert body["project_name"] == "Acme Corp"


def test_run_detail_serializer_includes_project_name(run_factory, suite_factory, project_factory):
    project = project_factory(name="Acme Corp")
    suite = suite_factory(project=project)
    run = run_factory(suite=suite)
    body = RunDetailSerializer(run).data
    assert body["project_name"] == "Acme Corp"


# ---- SPA wire format — sentinel keys --------------------------------------


@pytest.mark.parametrize(
    "serializer_cls,factory_name,expected_key",
    [
        (TestRowSerializer, "test_factory", "passed"),
        (RunDetailSerializer, "run_factory", "tests"),
        (RunSummarySerializer, "run_factory", "sequential_id"),
    ],
)
def test_spa_serializer_exposes_expected_key(
    serializer_cls,
    factory_name,
    expected_key,
    request,
):
    """Smoke test that each SPA serializer still exposes its identity-defining key.

    A failure here usually means a model field was renamed and the serializer
    `fields` list wasn't updated.
    """
    instance = request.getfixturevalue(factory_name)()
    body = serializer_cls(instance).data
    assert expected_key in body


def test_baseline_serializer_exposes_thumbnail_url(baseline_factory):
    body = BaselineSerializer(baseline_factory()).data
    assert "thumbnail_url" in body


# ---- SPA wire format — uses `passed`, never the legacy `pass` ------------


def test_spa_test_row_uses_passed_not_pass(test_factory):
    """The SPA's wire format uses `passed`; the legacy API wire format uses `pass`.

    api.md, "Serializers": SPA serializers expose the model field name.
    """
    body = TestRowSerializer(test_factory(passed=True)).data

    assert "passed" in body
    assert body["passed"] is True
    assert "pass" not in body, "leaked the legacy wire format into the SPA payload"


# ---- ProjectSerializer flattens suites -----------------------------------


def test_project_serializer_includes_suites(project_factory, suite_factory, run_factory):
    project = project_factory(name="Acme")
    suite_factory(project=project, name="Desktop")
    suite_factory(project=project, name="Mobile")

    body = ProjectSerializer(project).data
    suite_names = {s["name"] for s in body["suites"]}
    assert suite_names == {"Desktop", "Mobile"}


def test_project_serializer_suite_with_no_runs_has_null_latest_run(
    project_factory,
    suite_factory,
):
    """The legacy template crashed when suite.latest_run was nil. The SPA gets a clean null."""
    project = project_factory()
    suite_factory(project=project)

    body = ProjectSerializer(project).data
    assert body["suites"][0]["latest_run"] is None


def test_project_serializer_suite_with_runs_includes_latest_run_summary(
    project_factory,
    suite_factory,
    run_factory,
):
    project = project_factory()
    suite = suite_factory(project=project)
    run_factory(suite=suite)
    run_factory(suite=suite)

    body = ProjectSerializer(project).data
    assert body["suites"][0]["latest_run"]["sequential_id"] == 2


# ---- RunSummarySerializer.unbaselined ------------------------------------


def test_run_summary_unbaselined_counts_tests_with_no_baseline(suite_factory, run_factory, baseline_factory):
    """Tests whose key is absent from the suite's Baseline table count as unbaselined."""
    from core.models import Test

    suite = suite_factory()
    run = run_factory(suite=suite)
    # Create two tests with distinct keys
    t1 = Test.objects.create(run=run, name="home", browser="Chrome", size="1024")
    Test.objects.create(run=run, name="about", browser="Chrome", size="1024")
    # Baseline only t1's key
    baseline_factory(suite=suite, key=t1.key)

    body = RunSummarySerializer(run).data
    assert body["unbaselined"] == 1  # t2 has no baseline


def test_run_summary_unbaselined_is_zero_when_all_baselined(suite_factory, run_factory, baseline_factory):
    """Zero when every test key has a matching Baseline."""
    from core.models import Test

    suite = suite_factory()
    run = run_factory(suite=suite)
    t1 = Test.objects.create(run=run, name="home", browser="Chrome", size="1024")
    baseline_factory(suite=suite, key=t1.key)

    body = RunSummarySerializer(run).data
    assert body["unbaselined"] == 0


def test_run_summary_unbaselined_is_zero_when_run_has_no_tests(run_factory):
    """Runs with no tests at all return unbaselined == 0, not an error."""
    run = run_factory()
    body = RunSummarySerializer(run).data
    assert body["unbaselined"] == 0


# ---- build_run_counts helper -----------------------------------------------


def test_build_run_counts_returns_passing_failing_unbaselined_per_run(suite_factory, run_factory, baseline_factory):
    """Batch passing/failing/unbaselined counts for a set of runs into one dict.

    Verifies that:
    - Passing tests (passed=True) are counted correctly per run
    - Failing tests (passed=False) are counted correctly per run
    - Unbaselined tests (key not in baselined_keys) are counted correctly per run
    - Runs with zero tests are still present in the result (not sparse)
    """
    from core.models import Test

    suite = suite_factory()
    run_a = run_factory(suite=suite)
    run_b = run_factory(suite=suite)

    # Create tests for run_a: 2 passed (one baselined, one not), 1 failed
    t1_passed_baselined = Test.objects.create(
        run=run_a, name="home", browser="Chrome", size="1024", passed=True
    )
    Test.objects.create(run=run_a, name="about", browser="Chrome", size="1024", passed=True)
    Test.objects.create(run=run_a, name="contact", browser="Chrome", size="1024", passed=False)

    # Create a baseline for one of run_a's tests
    baseline_factory(suite=suite, key=t1_passed_baselined.key)

    # run_b has zero tests

    # Call build_run_counts
    baselined_keys = {t1_passed_baselined.key}
    result = build_run_counts([run_a.id, run_b.id], baselined_keys)

    # Verify run_a counts
    assert result[run_a.id]["passing"] == 2  # Both t1 and t2
    assert result[run_a.id]["failing"] == 1  # t3
    assert result[run_a.id]["unbaselined"] == 2  # t2 and t3 (t1 is baselined)

    # Verify run_b has zero counts (not sparse)
    assert result[run_b.id]["passing"] == 0
    assert result[run_b.id]["failing"] == 0
    assert result[run_b.id]["unbaselined"] == 0


def test_build_run_counts_returns_empty_dict_for_empty_run_ids(django_assert_num_queries):
    """Empty run_ids list returns empty dict without issuing any queries."""
    with django_assert_num_queries(0):
        result = build_run_counts([], set())
    assert result == {}


def test_run_summary_uses_run_counts_context_without_extra_queries(
    run_factory, test_factory, django_assert_num_queries
):
    """RunSummarySerializer reads run_counts context without querying the database.

    Verifies that when run_counts is provided in the serializer context, the serializer
    uses it instead of issuing queries for passing/failing/unbaselined counts.
    """
    run = run_factory()
    # Create some tests with real counts
    test_factory(run=run, passed=True)
    test_factory(run=run, passed=True)
    test_factory(run=run, passed=False)

    # Now serialize with fake counts in context
    with django_assert_num_queries(0):
        body = RunSummarySerializer(
            run,
            context={"run_counts": {run.id: {"passing": 11, "failing": 22, "unbaselined": 33}}}
        ).data

    # Verify it reads from context, not the database
    assert body["passing"] == 11
    assert body["failing"] == 22
    assert body["unbaselined"] == 33


# ---- TestHistoryEntrySerializer / serialize_test_history ------------------


def test_test_history_entry_serializer_uses_original_passed_not_passed(test_factory):
    """The history endpoint's whole purpose is exposing the immutable result;
    `passed` (mutable via promotion) must never leak into this serializer.
    """
    test = test_factory(passed=True, original_passed=False)
    body = TestHistoryEntrySerializer(test).data

    assert body["original_passed"] is False
    assert "passed" not in body


def test_test_history_entry_serializer_includes_run_fields(run_factory, test_factory):
    run = run_factory()
    test = test_factory(run=run)

    body = TestHistoryEntrySerializer(test).data

    assert body["run_id"] == run.id
    assert body["run_sequential_id"] == run.sequential_id
    assert body["run_created_at"] is not None


def test_serialize_test_history_returns_key_metadata_and_ordered_runs(
    suite_factory,
    run_factory,
    test_factory,
):
    suite = suite_factory(name="Desktop")
    run1 = run_factory(suite=suite)
    run2 = run_factory(suite=suite)

    older = test_factory(run=run1, name="Homepage", browser="Chrome", size="1024")
    newer = test_factory(run=run2, name="Homepage", browser="Chrome", size="1024")
    assert older.key == newer.key

    # Caller passes the ordered (newest-first) queryset result.
    body = serialize_test_history([newer, older], older.key)

    assert body["key"] == older.key
    assert body["name"] == "Homepage"
    assert body["browser"] == "Chrome"
    assert body["size"] == "1024"
    assert body["project_name"] == suite.project.name
    assert body["suite_slug"] == suite.slug
    assert [entry["id"] for entry in body["runs"]] == [newer.id, older.id]
